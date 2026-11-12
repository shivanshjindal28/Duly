import { useRef, useState, type DragEvent } from "react";
import { useNavigate } from "react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, FileUp, Loader2, ShieldCheck } from "lucide-react";
import { api, ApiError } from "../api/client";
import type { InvoiceDetail, SupplierOut } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { useTranslation } from "react-i18next";
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
  // Suppliers see their chosen language (English / Hindi); the staff UI stays in English.
  const { i18n } = useTranslation();
  const t = i18n.getFixedT(isClerk ? "en" : i18n.language);
  const hindi = !isClerk && i18n.language === "hi";

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
    <div className={`page upload-page${hindi ? " lang-hi" : ""}`} lang={hindi ? "hi" : "en"}>
      <header className="page-head">
        <p className="label">{isClerk ? "Upload on behalf of a supplier" : me?.supplier?.name}</p>
        <h1>{t("upload.title")}</h1>
        <p className="muted">{t("upload.formats")}</p>
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
            <p>{t("upload.drag")}</p>
          )}
          <button type="button" className="btn" onClick={() => input.current?.click()}>
            {file ? t("upload.choose_another") : t("upload.choose")}
          </button>
          <input
            ref={input}
            type="file"
            accept={ACCEPT}
            className="sr-only"
            aria-label={t("upload.file_label")}
            onChange={(e) => pick(e.target.files?.[0])}
          />
        </div>

        {upload.isError ? (
          <div className="alert alert-error" role="alert">
            <AlertTriangle size={16} aria-hidden="true" />
            <span>
              {upload.error instanceof ApiError ? upload.error.message : t("upload.failed")}
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
            {upload.isPending ? t("upload.busy") : t("upload.submit")}
          </button>
          {upload.isPending ? <span className="muted">{t("upload.slow")}</span> : null}
        </div>
      </section>

      <section className="upload-checks" aria-label={t("upload.checks_label")}>
        <ShieldCheck size={18} aria-hidden="true" />
        <p>{t("upload.checks")}</p>
      </section>
    </div>
  );
}
