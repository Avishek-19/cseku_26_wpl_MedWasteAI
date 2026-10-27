
"use client";

import { api } from "@/lib/api";
import { useState } from "react";

export function ManualReceive({
  recordId,
  quantity,
  onReceived,
}: {
  recordId: string;
  quantity: string | number;
  onReceived: () => void | Promise<void>;
}) {
  const [weight, setWeight] = useState(
    String(quantity)
  );
  const [note, setNote] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function receive() {
    setBusy(true);
    setError("");

    try {
      await api.post(
        `/api/v1/manual-workflow/waste/${recordId}/receipt`,
        {
          received_quantity: weight,
          note: note.trim(),
          confirm_physical_receipt: confirmed,
        }
      );

      await onReceived();
    } catch (e) {
      setError(
        e instanceof Error
          ? e.message
          : "Unable to receive this waste"
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mt-4 space-y-3 rounded-xl border border-violet-200 bg-violet-50 p-4">
      <h3 className="text-sm font-bold">
        Manual facility receipt (without GPS)
      </h3>

      <label className="block text-xs font-semibold">
        Actual received weight (kg)
        <input
          type="number"
          min="0.001"
          step="0.001"
          value={weight}
          onChange={(e) =>
            setWeight(e.target.value)
          }
          className="mt-1 w-full rounded-md border p-2"
        />
      </label>

      <label className="block text-xs font-semibold">
        Receiver name / condition / receiving note
        (12+ characters)

        <textarea
          value={note}
          onChange={(e) =>
            setNote(e.target.value)
          }
          className="mt-1 w-full rounded-md border p-2"
          rows={2}
          placeholder="Who received the shipment and what was checked?"
        />
      </label>

      <label className="flex items-start gap-2 text-xs">
        <input
          type="checkbox"
          checked={confirmed}
          onChange={(e) =>
            setConfirmed(e.target.checked)
          }
        />

        I personally confirm that this waste was
        handed to the facility. No GPS verification
        is claimed.
      </label>

      <button
        type="button"
        onClick={() => void receive()}
        disabled={
          busy ||
          !confirmed ||
          note.trim().length < 12 ||
          !(Number(weight) > 0)
        }
        className="rounded-lg bg-[#39245a] px-4 py-2 text-sm font-semibold text-white disabled:opacity-40"
      >
        {busy
          ? "Recording receipt..."
          : "Confirm manual receipt"}
      </button>

      {error && (
        <p
          role="alert"
          className="text-sm text-red-700"
        >
          {error}
        </p>
      )}
    </div>
  );
}
