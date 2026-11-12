# Architecture

This file is rendered as-is on the in-app **Architecture** page (`/architecture`), so the diagram we present is
the one in the app. Module names below are the real packages under `backend/app/`.

## Components

Duly is a side-car to the ERP: a React single-page app, a FastAPI backend with a deterministic rules engine at its
centre, and SQLite (Postgres-ready). Invoices are read by local OCR and rules (our setup runs in AI mode offline);
an optional AI integration can read documents and answer supplier questions, but it never decides.

```mermaid
flowchart TB
  subgraph People
    SUP[Supplier portal<br/>en / hi]
    AP[AP clerk]
    APR[Approvers L1-L3]
    ST[Stores]
    AUD[Auditor / Admin]
  end
  subgraph Frontend["Frontend · React + Vite"]
    UI[Role-aware screens<br/>invoice detail, dashboard,<br/>payments, audit, impact]
  end
  subgraph Backend["Backend · FastAPI"]
    API[api<br/>routers, RBAC, CSRF,<br/>supplier scoping]
    ING[ingestion<br/>hardening, text layer, OCR,<br/>QR verify, injection scan]
    AI[ai<br/>Claude extractor, offline parser,<br/>merge, cache]
    VAL[validation<br/>GSTIN, arithmetic, tax, HSN]
    ENG[engine<br/>3-way match + decision<br/>pure, no I/O, no AI]
    DUP[duplicates<br/>5 signals]
    WF[workflow<br/>DoA, SoD, MFA, SLA,<br/>receipts, bank changes]
    PAY[payments<br/>MSME guardian, payment run, TDS]
    ERP[erp<br/>Local adapter,<br/>S/4HANA stub]
    REP[reports<br/>controls, impact]
    CHAT[chat<br/>scoped tools, guardrails]
    CORE[core<br/>auth, crypto AES-GCM,<br/>audit hash chain, clock]
  end
  DB[(SQLite WAL<br/>Postgres via DATABASE_URL)]
  CLAUDE[[Claude API<br/>optional, AI_MODE]]
  IRP[[IRP signing key<br/>sandbox in demo]]

  SUP & AP & APR & ST & AUD --> UI
  UI -- "/api, session cookie" --> API
  API --> ING --> AI
  AI -. "page images + text only" .-> CLAUDE
  ING -. "verify RS256" .-> IRP
  ING --> ENG
  VAL --> ENG
  DUP --> ENG
  ENG --> WF --> PAY
  API --> CHAT -. "tool calls" .-> CLAUDE
  WF --> ERP
  API --> REP
  ENG & WF & PAY & CHAT --> CORE
  CORE --> DB
  ERP --> DB
```

- **AI never decides.** `engine` imports nothing from `ai` (a test enforces it). AI output is only a set of
  extracted values with confidence; low confidence goes to a human.
- **Untrusted input first.** Uploads are hardened (type, size, page count, active PDF content) and scanned for
  hidden instructions before any AI sees them.
- **Everything is audited.** Every match, approval, payment, review and refusal is a hash-chained event; the head
  is signed (Ed25519).

## Invoice lifecycle

```mermaid
sequenceDiagram
  autonumber
  actor S as Supplier
  participant D as Duly API
  participant A as AI / offline parser
  participant E as Rules engine
  actor C as AP clerk
  actor K as Stores
  actor F as Approver
  S->>D: Upload PDF or photo
  D->>D: Harden file, text layer or OCR, injection scan
  D->>A: Extract fields (quarantined if injection found)
  A-->>D: Values + confidence + location
  D->>D: Verify signed e-invoice QR
  D->>E: Invoice, PO, GR/SES, history, policy
  E-->>D: APPROVE / FLAG / BLOCK + reason codes
  alt Low confidence
    D->>C: Review highlighted fields (logged)
  end
  alt BLOCK missing GR
    K->>D: Post GR (MIGO 101)
    D->>E: Automatic re-match
  end
  alt APPROVE
    D->>F: Route by DoA (MFA above Rs 10 lakh, SoD enforced)
    F->>D: Approve
  end
  D->>D: Payment run: MSME first, discounts, TDS, UTR
  D-->>S: Status, reasons, expected payment (portal + chatbot)
```

## Data model (core)

```mermaid
erDiagram
  SUPPLIER ||--o{ PURCHASE_ORDER : "supplies"
  PURCHASE_ORDER ||--|{ PO_LINE : has
  PURCHASE_ORDER ||--o{ GOODS_RECEIPT : "received by"
  PURCHASE_ORDER ||--o{ SERVICE_ENTRY_SHEET : "accepted by"
  SUPPLIER ||--o{ INVOICE : issues
  INVOICE }o--|| DOCUMENT : "read from"
  INVOICE ||--|{ INVOICE_LINE : has
  INVOICE ||--o{ EXTRACTION_RESULT : "fields with confidence"
  INVOICE ||--o{ MATCH_RESULT : "decided by engine"
  MATCH_RESULT ||--o{ REASON_CODE : explains
  INVOICE ||--o{ APPROVAL_STEP : "routed to"
  INVOICE ||--o| PAYMENT : "paid by"
  SUPPLIER ||--o{ BANK_CHANGE_REQUEST : requests
  POLICY ||--o{ MATCH_RESULT : "versioned rules"
```

Audit events are a separate append-only table, linked to entities by type and id, so no business table can
rewrite history.

## Scaling path

- Stateless API: run more workers behind a load balancer; sessions are signed cookies.
- `DATABASE_URL` switches SQLite to Postgres; indexes on supplier, status, due dates and invoice numbers.
- Policies (tolerances, DoA, TDS, thresholds) are versioned data: finance changes rules without a release.
- The ERP adapter keeps SAP S/4HANA as the system of record (OData supplier-invoice post built by the stub).
- Production path: SSO via the company identity provider, the real IRP public key, BTP integration, pen test, DPIA.
