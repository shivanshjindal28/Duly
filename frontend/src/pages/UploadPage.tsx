import { useRef, useState, type DragEvent } from "react";
import { useNavigate } from "react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, FileUp, Loader2, ShieldCheck } from "lucide-react";
import { api, ApiError } from "../api/client";
import type { InvoiceDetail, SupplierOut } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import "./UploadPage.css";

const ACCEPT = ".pdf,.png,.jpg,.jpeg";

/** Supplier uploads own invoice; AP clerk uploads on behalf of a supplier (e.g. received by email). */
export function UploadPage() {
  const { me } = useAuth();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const input = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [supplierId, setSupplierId] = useState<string>("");
  const [dragging, setDragging] = useState(false);
  const isClerk = me?.role === "clerk";

  const suppliers = useQuery({
    queryKey: ["suppliers"],
    queryFn: () => api<SupplierOut[]>("/suppliers"),
    enabled: isClerk,
  });

  const upload = useMutation({
    mutationFn: async () => {
      const form = new FormData();
      form.append("file", file as File);
      if (isClerk && supplierId) form.append("supplier_id", supplierId);
      return api<InvoiceDetail>("/invoices/upload", { method: "POST", body: form });
    },
    onSuccess: (inv) => {
      qc.invalidateQueries({ queryKey: ["invoices"] });
      qc.setQueryData(["invoice", String(inv.id)], inv);
      navigate(`/invoices/${inv.id}`);
    },
  });

  function pick(f: File | undefined | null) {
    if (f) {
      setFile(f);
      upload.reset();
    }
  }

  function onDrop(e: DragEvent) {
    e.preventDefault();
    setDragging(false);
    pick(e.dataTransfer.files?.[0]);
  }

  return (
    <div className="page upload-page">
      <header className="page-head">
        <p className="label">{isClerk ? "Upload on behalf of a supplier" : me?.supplier?.name}</p>
        <h1>Upload invoice</h1>
        <p className="muted">PDF, PNG or JPG up to 10 MB. Scans and phone photos are read with on-device OCR.</p>
      </header>

      <section className="panel upload-panel">
        {isClerk ? (
          <label className="field">
            <span>Supplier (optional: Duly identifies it from the GSTIN on the invoice)</span>
            <select className="input" value={supplierId} onChange={(e) => setSupplierId(e.target.value)}>
              <option value="">Identify from the document</option>
              {(suppliers.data ?? []).map((s) => (
                <option key={s.id} value={s.id}>
                  {s.name} ({s.code})
                </option>
              ))}
            </select>
          </label>
        ) : null}

        <div
          className={`dropzone${dragging ? " is-dragging" : ""}${file ? " has-file" : ""}`}
          onDragOver={(e) => {
            e.preventDefault();
            setDragging(true);
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={onDrop}
        >
          <FileUp size={28} aria-hidden="true" />
          {file ? (
            <p>
              <strong>{file.name}</strong> <span className="muted">({(file.size / 1024).toFixed(0)} KB)</span>
            </p>
          ) : (
            <p>Drag a file here, or</p>
          )}
          <button type="button" className="btn" onClick={() => input.current?.click()}>
            {file ? "Choose another file" : "Choose file"}
          </button>
          <input
            ref={input}
            type="file"
            accept={ACCEPT}
            className="sr-only"
            aria-label="Invoice file"
            onChange={(e) => pick(e.target.files?.[0])}
          />
        </div>

        {upload.isError ? (
          <div className="alert alert-error" role="alert">
            <AlertTriangle size={16} aria-hidden="true" />
            <span>
              {upload.error instanceof ApiError ? upload.error.message : "Upload failed. Is the server running?"}
            </span>
          </div>
        ) : null}

        <div className="upload-actions">
          <button
            type="button"
            className="btn btn-primary"
            disabled={!file || upload.isPending}
            onClick={() => upload.mutate()}
          >
            {upload.isPending ? <Loader2 size={16} className="spin" aria-hidden="true" /> : <FileUp size={16} aria-hidden="true" />}
            {upload.isPending ? "Reading and checking..." : "Upload and check"}
          </button>
          {upload.isPending ? <span className="muted">Scans can take up to 20 seconds to read.</span> : null}
        </div>
      </section>

      <section className="upload-checks" aria-label="What happens to your file">
        <ShieldCheck size={18} aria-hidden="true" />
        <p>
          Every file is checked before anything reads it: type and content must match, size and page limits, PDFs with
          scripts or embedded files are refused, and photo metadata (such as location) is removed. The file is stored
          under a random name and fingerprinted (SHA-256).
        </p>
      </section>
    </div>
  );
}
