# RAG Flow: UML and User-Flow Diagrams

This page traces every RAG step in FinRAG to the function and file that performs it:
loading, chunking, "embedding" (vectorising), storing, retrieving, sending to the LLM,
and checking the answer.

Diagrams use Mermaid and render directly on GitHub.

- [1. Vector storage and matching: how FinRAG actually does it](#1-vector-storage-and-matching-how-finrag-actually-does-it)
- [2. UML class diagram: the RAG components](#2-uml-class-diagram-the-rag-components)
- [3. UML activity diagram: ingestion (file to stored chunks)](#3-uml-activity-diagram-ingestion-file-to-stored-chunks)
- [4. UML sequence diagram: ingestion](#4-uml-sequence-diagram-ingestion)
- [5. UML activity diagram: vectorising and matching](#5-uml-activity-diagram-vectorising-and-matching)
- [6. UML activity diagram: question to answer](#6-uml-activity-diagram-question-to-answer)
- [7. UML sequence diagram: question to answer (including the LLM call)](#7-uml-sequence-diagram-question-to-answer-including-the-llm-call)
- [8. User flow diagram](#8-user-flow-diagram)
- [9. Function reference](#9-function-reference)
- [10. Swapping in a real vector database](#10-swapping-in-a-real-vector-database)

---

## 1. Vector storage and matching: how FinRAG actually does it

> **FinRAG does not use an external vector database, and it does not match queries to
> clusters or graph nodes.** This is a deliberate privacy choice (GDPR Art. 25 / Art. 44):
> no document text is sent to an embedding API or a hosted vector store.

| Question | Answer in FinRAG |
|---|---|
| Where are chunks stored? | `TenantStore` in `finrag/retrieval/store.py`. One Fernet-encrypted file per tenant: `data/tenants/<tenant>/store.enc`. It holds pseudonymised chunk text and metadata, not vectors. |
| What is the "embedding" step? | `HybridIndex.__init__` in `finrag/retrieval/index.py`. Each chunk is tokenised (`tokenize`), its words and word pairs are hashed into a 262,144-dimension sparse vector (`_features`), weighted by TF-IDF and normalised to unit length (`_weight`). There is no neural embedding model. |
| Where do the vectors live? | In memory only, inside `HybridIndex`. `TenantStore.search` builds the index the first time it is needed and throws it away whenever documents change (`TenantStore._save` sets `_index = None`). Vectors are never written to disk. |
| How is the best match found? | `HybridIndex.search`. **Exact search over every chunk** in the tenant: each chunk gets `0.6 × BM25 keyword score (normalised) + 0.4 × cosine similarity`. Quarantined chunks are skipped. The top `k` (default 6) above `min_relevance` (default 0.05) are kept. |
| Clusters / nodes (IVF, HNSW)? | None. Those are approximate-search structures that large vector databases use to avoid scoring every vector. FinRAG scores every chunk, which is exact and fast enough for thousands of chunks per tenant. |
| When would I need a vector DB? | When a tenant has hundreds of thousands of chunks, or you want neural (meaning-based) embeddings. See [section 10](#10-swapping-in-a-real-vector-database). |

---

## 2. UML class diagram: the RAG components

```mermaid
classDiagram
    direction LR

    class FinRAGPipeline {
        <<finrag/pipeline.py>>
        +ingest(principal, filename, data, lawful_basis, purpose) IngestReport
        +ask(principal, question, reidentify) Answer
        -_ctx(tenant) _TenantContext
        -_authorise(principal, permission, action)
        -_assess(hits, out, query_flags, truncated)
    }

    class Loaders {
        <<finrag/ingestion/loaders.py>>
        +load_document(filename, data, settings) LoadedDocument
        +sanitize_filename(name) str
        -_load_pdf(data, settings)
        -_load_xlsx(data, settings)
        -_inspect_xlsx_archive(data, settings)
        -_load_csv(data, settings)
        -_load_text(data, settings)
    }

    class Chunker {
        <<finrag/ingestion/chunker.py>>
        +chunk_sections(sections, size, overlap) list~Chunk~
        -_split_text(text, size, overlap)
        -_split_table(section, size)
    }

    class Pseudonymiser {
        <<finrag/security/pii.py>>
        +pseudonymise(text, doc_id) tuple
        +token_for(pii_type, value) str
        +reidentify(text) str
    }

    class PIIDetector {
        <<finrag/security/pii.py>>
        +detect(text) list~PIISpan~
        +special_categories(text) list
    }

    class PseudonymVault {
        <<finrag/security/pii.py>>
        +put(token, pii_type, value, doc_id)
        +save()
        +lookup(token) str
    }

    class TenantStore {
        <<finrag/retrieval/store.py>>
        +documents dict
        +chunks list~ChunkRecord~
        +add_document(record, chunks)
        +search(query, top_k) list
        -_save()
        -_load()
    }

    class HybridIndex {
        <<finrag/retrieval/index.py>>
        -_tf list
        -_idf dict
        -_vectors list~sparse vector~
        +search(query, top_k, exclude) list~SearchHit~
        +expand(tokens) list
        -_weight(feats) dict
    }

    class Guardrails {
        <<finrag/security/guardrails.py>>
        +check_query(query, max_chars, detector)
        +screen_context(chunk_text)
        +check_answer(answer, context_by_label, canary, detector)
        +extract_numbers(text)
    }

    class Prompts {
        <<finrag/generation/prompts.py>>
        +SYSTEM_PROMPT
        +SYSTEM_CANARY
        +build_user_message(question, sources) str
    }

    class AnswerGenerator {
        <<interface finrag/generation/llm.py>>
        +generate(question, sources) LLMResult
    }
    class AnthropicLLM {
        <<finrag/generation/llm.py>>
        +generate(question, sources) LLMResult
    }
    class OfflineLLM {
        <<finrag/generation/llm.py>>
        +generate(question, sources) LLMResult
    }

    FinRAGPipeline --> Loaders : 1 parse
    FinRAGPipeline --> Pseudonymiser : 2 mask PII
    FinRAGPipeline --> Chunker : 3 chunk
    FinRAGPipeline --> Guardrails : screen and check
    FinRAGPipeline --> TenantStore : 4 store and search
    TenantStore --> HybridIndex : builds lazily
    Pseudonymiser --> PIIDetector
    Pseudonymiser --> PseudonymVault
    FinRAGPipeline --> AnswerGenerator : 5 generate
    AnswerGenerator <|.. AnthropicLLM
    AnswerGenerator <|.. OfflineLLM
    AnthropicLLM --> Prompts : builds request
```

---

## 3. UML activity diagram: ingestion (file to stored chunks)

```mermaid
flowchart TD
    start((Start)) --> A["Upload file<br/><i>api.py · upload_document</i><br/><i>or cli.py · _run ingest</i>"]
    A --> B["Check INGEST permission<br/><i>pipeline.py · _authorise</i>"]
    B --> C["Validate and parse file<br/><i>loaders.py · load_document</i>"]
    C --> C1{"Which file type?"}
    C1 -->|PDF| P1["<i>_load_pdf</i><br/>one Section per page"]
    C1 -->|XLSX| X0["<i>_inspect_xlsx_archive</i><br/>zip bomb / macro / link check"] --> X1["<i>_load_xlsx</i><br/>header + rows per sheet"]
    C1 -->|CSV| V1["<i>_load_csv</i><br/>header + rows"]
    C1 -->|TXT / MD| T1["<i>_load_text</i>"]
    P1 & X1 & V1 & T1 --> D{"Valid?"}
    D -->|No| R1["Raise UnsupportedDocumentError<br/>audit: ingest rejected"] --> stop1((End))
    D -->|Yes| E{"Same SHA-256 already stored?<br/><i>store.py · find_by_hash</i>"}
    E -->|Yes| R2["Return existing doc<br/>duplicate = true"] --> stop2((End))
    E -->|No| F["Scan for special-category data<br/><i>pii.py · PIIDetector.special_categories</i>"]
    F --> G["Check lawful basis, purpose, Art. 9 condition<br/><i>gdpr.py · validate_processing</i><br/>Set expiry<br/><i>gdpr.py · retention_deadline</i>"]
    G --> G1{"Compliant?"}
    G1 -->|No| R3["Raise ComplianceError<br/>audit: ingest rejected"] --> stop3((End))
    G1 -->|Yes| H["Replace PII with tokens in every section, row and header<br/><i>pii.py · Pseudonymiser.pseudonymise</i><br/>token map saved to <i>PseudonymVault.put</i>"]
    H --> I["Split into chunks<br/><i>chunker.py · chunk_sections</i><br/>text → <i>_split_text</i> · tables → <i>_split_table</i>"]
    I --> J["Screen each chunk for hidden instructions<br/><i>guardrails.py · screen_context</i><br/>suspicious → quarantined = true"]
    J --> K["Save encrypted chunks + metadata<br/><i>store.py · TenantStore.add_document → _save</i><br/>save vault <i>PseudonymVault.save</i>"]
    K --> L["Audit: ingest success<br/><i>audit.py · AuditLog.record</i>"]
    L --> M["Return IngestReport"] --> stop((End))
```

No vectors are created at upload time. They are built on the first search after a change
(see section 5).

---

## 4. UML sequence diagram: ingestion

```mermaid
sequenceDiagram
    autonumber
    actor U as Analyst
    participant API as api.py<br/>upload_document
    participant P as pipeline.py<br/>FinRAGPipeline.ingest
    participant L as loaders.py<br/>load_document
    participant G as gdpr.py
    participant X as pii.py<br/>Pseudonymiser
    participant V as pii.py<br/>PseudonymVault
    participant C as chunker.py<br/>chunk_sections
    participant GR as guardrails.py<br/>screen_context
    participant S as store.py<br/>TenantStore
    participant A as audit.py<br/>AuditLog

    U->>API: POST /v1/documents (file, lawful_basis, purpose)
    API->>P: ingest(principal, filename, bytes, ...)
    P->>P: _authorise(INGEST)
    P->>L: load_document(filename, bytes, settings)
    L-->>P: LoadedDocument(sections)
    P->>S: find_by_hash(sha256)
    S-->>P: None (new document)
    P->>X: detector.special_categories(raw text)
    P->>G: validate_processing(...), retention_deadline(...)
    G-->>P: basis, purpose, expires_at
    loop every section, header and row
        P->>X: pseudonymise(text, doc_id)
        X->>V: put(token, type, value, doc_id)
        X-->>P: text with tokens
    end
    P->>C: chunk_sections(sections, 1200, 150)
    C-->>P: list of Chunk
    loop every chunk
        P->>GR: screen_context(chunk.text)
        GR-->>P: findings (empty = safe)
    end
    P->>S: add_document(record, chunk_records)
    S->>S: _save() encrypt to store.enc, drop old index
    P->>V: save() encrypt to vault.enc
    P->>A: record("ingest", ...)
    P-->>API: IngestReport
    API-->>U: 201 Created
```

---

## 5. UML activity diagram: vectorising and matching

This is the "embedding" and "vector search" part of the pipeline. Everything happens
inside `finrag/retrieval/index.py` and `finrag/retrieval/store.py`.

```mermaid
flowchart TD
    Q0["<i>pipeline.py · ask</i> calls<br/><i>store.py · TenantStore.search(question, top_k)</i>"] --> Q1{"Index already built?<br/>(<i>self._index</i>)"}

    Q1 -->|No| B0["Build index from all tenant chunks<br/><i>index.py · HybridIndex.__init__</i>"]
    subgraph EMBED ["Vectorise chunks (HybridIndex.__init__)"]
        B0 --> B1["Split each chunk into words and numbers<br/><i>tokenize</i>"]
        B1 --> B2["Keyword statistics for BM25<br/>term frequency, document frequency, IDF"]
        B1 --> B3["Hash unigrams + bigrams into a<br/>262,144-dimension sparse vector<br/><i>_features</i> (blake2b mod 2^18)"]
        B3 --> B4["Weight: (1 + log tf) × idf<br/>normalise to unit length<br/><i>_weight</i>"]
        B2 & B4 --> B5[("In-memory index<br/>_tf · _idf · _vectors<br/>not written to disk")]
    end
    Q1 -->|Yes| S0
    B5 --> S0

    subgraph MATCH ["Match the question (HybridIndex.search)"]
        S0["Tokenise question<br/><i>tokenize</i>"] --> S1["Add finance synonyms<br/><i>expand</i> e.g. revenue → sales, turnover"]
        S1 --> S2["BM25 score for every chunk<br/>synonyms count half"]
        S0 --> S3["Vectorise question<br/><i>_features → _weight</i>"]
        S3 --> S4["Cosine similarity with every chunk vector"]
        S2 & S4 --> S5["score = 0.6 × BM25 / max BM25 + 0.4 × cosine<br/>skip quarantined chunks"]
        S5 --> S6["Sort and keep top_k = 6"]
    end

    S6 --> F1["<i>pipeline.py · ask</i><br/>drop hits below min_relevance = 0.05<br/>re-check each chunk with <i>screen_context</i>"]
    F1 --> F2["Label survivors S1, S2, … as PromptSource"]
```

There is no cluster or node lookup: step S2/S4 visits every chunk of the tenant.

---

## 6. UML activity diagram: question to answer

```mermaid
flowchart TD
    start((Start)) --> A["Question arrives<br/><i>api.py · query</i> or <i>cli.py · _run ask</i>"]
    A --> B["Authenticate API key<br/><i>api.py · get_principal → access.py · APIKeyAuthenticator.authenticate</i>"]
    B --> C["Check QUERY permission and rate limit<br/><i>pipeline.py · _authorise</i>, <i>access.py · RateLimiter.allow</i>"]
    C --> D["Input guardrails<br/><i>guardrails.py · check_query</i><br/>injection · banned practice · high-risk decision · length"]
    D --> D1{"Allowed?"}
    D1 -->|No| X1["Blocked answer + explanation<br/><i>pipeline.py · _block_message</i>"] --> stop1((End))
    D1 -->|Yes| E["Replace PII in question with the same tokens, store nothing<br/><i>pii.py · Pseudonymiser.pseudonymise(text, None)</i>"]
    E --> F["Retrieve top chunks<br/><i>store.py · TenantStore.search → index.py · HybridIndex.search</i><br/>(section 5)"]
    F --> F1{"Any relevant chunks?"}
    F1 -->|No| X2["'Documents do not contain enough information'<br/>LLM is NOT called"] --> stop2((End))
    F1 -->|Yes| G["Build prompt<br/><i>prompts.py · SYSTEM_PROMPT + build_user_message</i><br/>chunks fenced in &lt;source&gt; tags"]
    G --> H{"Provider?<br/><i>llm.py · build_generator</i>"}
    H -->|anthropic| H1["Send to Claude<br/><i>llm.py · AnthropicLLM.generate</i><br/>client.beta.messages.create, no tools"]
    H -->|offline| H2["Pick best source lines locally<br/><i>llm.py · OfflineLLM.generate</i>"]
    H1 & H2 --> I{"Model refused?"}
    I -->|Yes| X3["Declined answer"] --> stop3((End))
    I -->|No| J["Output guardrails<br/><i>guardrails.py · check_answer</i><br/>canary leak · PII · citations · figures"]
    J --> J1{"System prompt leaked?"}
    J1 -->|Yes| X4["Answer withheld"] --> stop4((End))
    J1 -->|No| K["Confidence + review reasons<br/><i>pipeline.py · _assess</i>"]
    K --> L{"reidentify requested?"}
    L -->|Yes, dpo role| L1["Tokens → original values<br/><i>pii.py · Pseudonymiser.reidentify</i>, audited"]
    L -->|No| M
    L1 --> M["Attach AI label + disclaimer<br/><i>transparency.py · label_output</i>"]
    M --> N["Audit query trace<br/><i>audit.py · AuditLog.record</i>"]
    N --> O["Return Answer: text, citations, confidence,<br/>requires_human_review"] --> stop((End))
```

---

## 7. UML sequence diagram: question to answer (including the LLM call)

```mermaid
sequenceDiagram
    autonumber
    actor U as User
    participant API as api.py<br/>query
    participant P as pipeline.py<br/>FinRAGPipeline.ask
    participant GR as guardrails.py
    participant X as pii.py<br/>Pseudonymiser
    participant S as store.py<br/>TenantStore
    participant IX as index.py<br/>HybridIndex
    participant PR as prompts.py
    participant LLM as llm.py<br/>AnthropicLLM
    participant C as Claude API
    participant T as transparency.py
    participant A as audit.py

    U->>API: POST /v1/query {question}
    API->>API: get_principal(X-API-Key)
    API->>P: ask(principal, question)
    P->>P: _authorise(QUERY), RateLimiter.allow
    P->>GR: check_query(question)
    GR-->>P: allowed, sanitized text, flags
    P->>X: pseudonymise(question, None)
    X-->>P: safe_question (PII → tokens)
    P->>S: search(safe_question, top_k=6)
    alt index not built yet
        S->>IX: HybridIndex(all chunk texts)
        Note over IX: tokenize → _features → _weight<br/>sparse TF-IDF vectors in memory
    end
    S->>IX: search(query, 6, exclude=quarantined)
    Note over IX: score every chunk:<br/>0.6 × BM25 + 0.4 × cosine
    IX-->>S: top SearchHits
    S-->>P: (ChunkRecord, score) list
    P->>GR: screen_context(chunk) for each hit
    P->>P: label sources S1..Sn
    P->>LLM: generate(safe_question, sources)
    LLM->>PR: build_user_message(question, sources)
    PR-->>LLM: fenced <source> blocks + question
    LLM->>C: beta.messages.create(model, system=SYSTEM_PROMPT,<br/>thinking adaptive, fallbacks default, no tools)
    C-->>LLM: response (stop_reason, content)
    LLM-->>P: LLMResult(text, model, refused, truncated)
    P->>GR: check_answer(text, sources, SYSTEM_CANARY)
    GR-->>P: sanitized text, citations, unverified numbers
    P->>P: _assess() → confidence, review reasons
    opt reidentify and dpo role
        P->>X: reidentify(text)
    end
    P->>T: label_output(model, requires_review)
    P->>A: record("query", ...)
    P-->>API: Answer
    API-->>U: 200 answer, citations, confidence, label
```

---

## 8. User flow diagram

What each type of user does, and what they see at every decision point.

```mermaid
flowchart TD
    U0([User opens FinRAG<br/>CLI or API client]) --> U1{"Has a valid API key?"}
    U1 -->|No| E1[/"401 Unauthorised"/]
    U1 -->|Yes| U2{"What do they want to do?"}

    %% Upload path
    U2 -->|Upload a document<br/>analyst| A1["Choose file: PDF, XLSX, CSV, TXT, MD"]
    A1 --> A2["Enter lawful basis, purpose,<br/>optional retention days"]
    A2 --> A3{"File and GDPR checks pass?"}
    A3 -->|No| E2[/"422 with reason, e.g.<br/>'macro-enabled workbooks are not accepted'<br/>'an Art. 9(2) condition is required'"/]
    A3 -->|Yes| A4[/"201: doc id, chunks, PII masked count,<br/>quarantined chunks, expiry date"/]
    A4 --> U2

    %% Ask path
    U2 -->|Ask a question<br/>viewer or analyst| Q1["Type question, e.g.<br/>'What was net income in FY2024?'"]
    Q1 --> Q2{"Question allowed?"}
    Q2 -->|"Injection attempt"| E3[/"'Blocked by a security policy'"/]
    Q2 -->|"Credit scoring / hiring decision"| E4[/"'Not designed to make decisions about individuals'"/]
    Q2 -->|"Too many requests"| E5[/"429, retry after 60 s"/]
    Q2 -->|Yes| Q3{"Relevant content in my documents?"}
    Q3 -->|No| E6[/"'Documents do not contain enough information'"/]
    Q3 -->|Yes| Q4[/"Answer with [S1] citations, confidence,<br/>AI disclosure, disclaimer"/]
    Q4 --> Q5{"requires_human_review?"}
    Q5 -->|Yes| Q6["Check cited sources / escalate to a reviewer<br/>reasons e.g. unverified_figures"]
    Q5 -->|No| Q7["Use the answer"]
    Q6 --> U2
    Q7 --> U2
    Q4 --> Q8{"Need the real names / emails<br/>behind the tokens?"}
    Q8 -->|"dpo role"| Q9["Ask again with reidentify = true<br/>(audited)"]
    Q8 -->|"other roles"| E7[/"403 Forbidden"/]

    %% DPO path
    U2 -->|Handle a GDPR request<br/>dpo| D1{"Request type"}
    D1 -->|Access / portability| D2[/"Export of excerpts mentioning<br/>the person, JSON or CSV"/]
    D1 -->|Erasure| D3[/"Identifier erased:<br/>vault entry destroyed,<br/>tokens replaced with [ERASED]"/]
    D1 -->|Retention| D4[/"Expired documents purged"/]
    D1 -->|Audit| D5[/"Audit chain valid / tampered"/]
```

---

## 9. Function reference

Line numbers are as of this commit and move as the code changes; search for the function
name if they drift.

### Ingestion: file to stored chunks

| # | Step | Function | File |
|---|---|---|---|
| 1 | Receive upload | `upload_document` | `finrag/api.py:167` |
| 2 | Orchestrate ingestion | `FinRAGPipeline.ingest` | `finrag/pipeline.py:170` |
| 3 | Permission check | `FinRAGPipeline._authorise` | `finrag/pipeline.py:159` |
| 4 | Validate + dispatch by type | `load_document` | `finrag/ingestion/loaders.py:229` |
| 4a | PDF pages → sections | `_load_pdf` | `finrag/ingestion/loaders.py:101` |
| 4b | XLSX safety check | `_inspect_xlsx_archive` | `finrag/ingestion/loaders.py:125` |
| 4c | XLSX sheets → header + rows | `_load_xlsx` | `finrag/ingestion/loaders.py:150` |
| 4d | CSV → header + rows | `_load_csv` | `finrag/ingestion/loaders.py:187` |
| 4e | Text / Markdown | `_load_text` | `finrag/ingestion/loaders.py:214` |
| 5 | Duplicate check | `TenantStore.find_by_hash` | `finrag/retrieval/store.py:152` |
| 6 | Special-category scan | `PIIDetector.special_categories` | `finrag/security/pii.py:184` |
| 7 | GDPR checks + expiry | `validate_processing`, `retention_deadline` | `finrag/governance/gdpr.py` |
| 8 | Find PII | `PIIDetector.detect` | `finrag/security/pii.py:158` |
| 9 | Replace PII with tokens | `Pseudonymiser.pseudonymise` | `finrag/security/pii.py:294` |
| 10 | Record token → value | `PseudonymVault.put` / `save` | `finrag/security/pii.py:229`, `:238` |
| 11 | **Split into chunks** | `chunk_sections` | `finrag/ingestion/chunker.py:78` |
| 11a | Paragraph chunks with overlap | `_split_text` | `finrag/ingestion/chunker.py:32` |
| 11b | Table chunks repeating the header | `_split_table` | `finrag/ingestion/chunker.py:61` |
| 12 | Quarantine hidden instructions | `screen_context` | `finrag/security/guardrails.py:159` |
| 13 | Encrypt + save chunks | `TenantStore.add_document` → `_save` | `finrag/retrieval/store.py:113`, `:104` |

### Vectorising and matching

| # | Step | Function | File |
|---|---|---|---|
| 14 | Search entry point, builds index lazily | `TenantStore.search` | `finrag/retrieval/store.py:156` |
| 15 | **Vectorise all chunks** | `HybridIndex.__init__` | `finrag/retrieval/index.py:88` |
| 15a | Words / numbers | `tokenize` | `finrag/retrieval/index.py:60` |
| 15b | Hash into 2^18-dim sparse vector | `_features` | `finrag/retrieval/index.py:70` |
| 15c | TF-IDF weight + unit length | `HybridIndex._weight` | `finrag/retrieval/index.py:108` |
| 16 | Finance synonym expansion | `HybridIndex.expand` | `finrag/retrieval/index.py:115` |
| 17 | **Score every chunk (BM25 + cosine), top k** | `HybridIndex.search` | `finrag/retrieval/index.py:122` |

### Question to answer

| # | Step | Function | File |
|---|---|---|---|
| 18 | Receive question | `query` | `finrag/api.py:206` |
| 19 | Authenticate | `get_principal` → `APIKeyAuthenticator.authenticate` | `finrag/api.py:119`, `finrag/security/access.py` |
| 20 | Orchestrate answering | `FinRAGPipeline.ask` | `finrag/pipeline.py:268` |
| 21 | Input guardrails | `check_query` | `finrag/security/guardrails.py:118` |
| 22 | Mask PII in the question | `Pseudonymiser.pseudonymise(text, None)` | `finrag/security/pii.py:294` |
| 23 | Retrieve (steps 14 to 17) | `TenantStore.search` | `finrag/retrieval/store.py:156` |
| 24 | Choose provider | `build_generator` | `finrag/generation/llm.py:144` |
| 25 | Build prompt | `SYSTEM_PROMPT`, `build_user_message` | `finrag/generation/prompts.py:76` |
| 26 | **Send to LLM** | `AnthropicLLM.generate` (Claude) | `finrag/generation/llm.py:73` |
| 26b | Local alternative | `OfflineLLM.generate` | `finrag/generation/llm.py:119` |
| 27 | Output guardrails | `check_answer` | `finrag/security/guardrails.py:201` |
| 28 | Confidence + review flag | `FinRAGPipeline._assess` | `finrag/pipeline.py:385` |
| 29 | Optional re-identification | `Pseudonymiser.reidentify` | `finrag/security/pii.py:318` |
| 30 | AI label | `label_output` | `finrag/governance/transparency.py` |
| 31 | Audit trace | `AuditLog.record` | `finrag/security/audit.py` |

---

## 10. Swapping in a real vector database

If you need neural embeddings or very large corpora, only `TenantStore.search` and
`HybridIndex` change. The rest of the pipeline (PII masking, guardrails, prompt, LLM,
audit) stays as it is.

```mermaid
flowchart LR
    subgraph Today ["Today (built in)"]
        T1["chunk text<br/>(pseudonymised)"] --> T2["HybridIndex<br/>sparse hashed TF-IDF + BM25"] --> T3["exact score of<br/>every chunk"]
    end
    subgraph Option ["Possible extension (not implemented)"]
        O1["chunk text<br/>(pseudonymised)"] --> O2["self-hosted embedding model<br/>dense vectors"] --> O3[("vector DB with per-tenant<br/>collections, encryption at rest")] --> O4["approximate nearest-neighbour<br/>search (e.g. HNSW graph nodes)"]
    end
```

Requirements to keep the same guarantees:

- Embed only the **pseudonymised** chunk text, never the raw file.
- Prefer a **self-hosted** embedding model, or put a DPA in place for a hosted one
  (GDPR Art. 28 / 44).
- One collection or namespace per tenant, with the tenant taken from the credential
  (OWASP LLM08).
- Encryption at rest, and delete vectors whenever `delete_document`, `erase_subject` or
  `purge_expired` runs (GDPR Art. 17 / 5(1)(e)).
