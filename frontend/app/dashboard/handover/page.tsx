
"use client";

import { useDeferredEffect } from "@/hooks/use-deferred-effect";
import { api } from "@/lib/api";
import { useRef, useState } from "react";

type PickupState = {
  pickup_status: string;
  stop_status: string | null;
  arrived: boolean;
  collected: boolean;
  in_transit: boolean;
};

type BarcodeDetectorType = new (
  options: { formats: string[] }
) => {
  detect: (
    video: HTMLVideoElement
  ) => Promise<{ rawValue: string }[]>;
};

const input =
  "mt-2 w-full rounded-xl border border-gray-300 bg-white px-4 py-3 text-sm";

const button =
  "rounded-xl bg-[#39245a] px-5 py-3 text-sm font-semibold text-white disabled:opacity-40";

export default function HandoverPage() {
  const [pickupId, setPickupId] = useState("");
  const [qr, setQr] = useState("");
  const [note, setNote] = useState("");
  const [attested, setAttested] = useState(false);

  const [arrived, setArrived] = useState(false);
  const [collected, setCollected] = useState(false);
  const [transit, setTransit] = useState(false);

  const [weight, setWeight] = useState("10");
  const [packaging, setPackaging] = useState("sealed");
  const [exception, setException] = useState("");

  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);

  const videoRef = useRef<HTMLVideoElement>(null);
  const streamRef = useRef<MediaStream | null>(null);

  useDeferredEffect(() => {
    const id = new URLSearchParams(
      window.location.search
    ).get("pickup_id");

    if (id && /^[a-f0-9-]{36}$/i.test(id)) {
      setPickupId(id);
    }
  }, []);

  useDeferredEffect(() => {
    if (!pickupId) return;

    void api
      .get<PickupState>(
        `/api/v1/manual-workflow/pickups/${pickupId}/state`
      )
      .then((data) => {
        setArrived(data.arrived);
        setCollected(data.collected);
        setTransit(data.in_transit);
      })
      .catch((e: unknown) => {
        setMessage(
          e instanceof Error
            ? e.message
            : "Pickup could not be loaded"
        );
      });
  }, [pickupId]);

  const stopCamera = () => {
    streamRef.current
      ?.getTracks()
      .forEach((track) => track.stop());

    streamRef.current = null;
  };

  async function scanQR() {
    const BrowserDetector = (
      window as typeof window & {
        BarcodeDetector?: BarcodeDetectorType;
      }
    ).BarcodeDetector;

    if (!BrowserDetector) {
      setMessage(
        "Camera QR detection is not supported here. Paste the hospital QR reference instead."
      );
      return;
    }

    try {
      const stream =
        await navigator.mediaDevices.getUserMedia({
          video: { facingMode: "environment" },
        });

      streamRef.current = stream;

      if (!videoRef.current) {
        throw new Error("Camera video not available");
      }

      videoRef.current.srcObject = stream;
      await videoRef.current.play();

      const detector = new BrowserDetector({
        formats: ["qr_code"],
      });

      for (let i = 0; i < 25; i += 1) {
        const found = await detector.detect(
          videoRef.current
        );

        if (found[0]?.rawValue) {
          setQr(found[0].rawValue);
          setMessage("Hospital QR scanned.");
          return;
        }

        await new Promise((resolve) =>
          setTimeout(resolve, 200)
        );
      }

      setMessage(
        "No QR detected. Enter the reference manually."
      );
    } catch (error) {
      setMessage(
        error instanceof Error
          ? error.message
          : "Camera unavailable"
      );
    } finally {
      stopCamera();
    }
  }

  async function manualArrival() {
    if (
      !window.confirm(
        "Confirm you are physically at the hospital and received its QR? This is NOT GPS verification."
      )
    ) {
      return;
    }

    setBusy(true);
    setMessage("");

    try {
      await api.post(
        `/api/v1/manual-workflow/pickups/${pickupId}/arrival`,
        {
          handover_qr: qr.trim(),
          note: note.trim(),
          confirm_hospital_presence: attested,
        }
      );

      setArrived(true);

      setMessage(
        "Driver-attested hospital arrival saved. GPS has not been verified. Now confirm the measured handover."
      );
    } catch (error) {
      setMessage(
        error instanceof Error
          ? error.message
          : "Manual arrival failed"
      );
    } finally {
      setBusy(false);
    }
  }

  async function confirmHandover() {
    setBusy(true);
    setMessage("");

    try {
      await api.post(
        `/api/v1/pickups/${pickupId}/collect`,
        {
          handover_qr: qr.trim(),
          actual_weight_kg: weight,
          packaging_condition: packaging,
          exception_reason: exception.trim() || null,
        }
      );

      setCollected(true);

      setMessage(
        "Waste handover collected and recorded. You can now send it to the treatment facility."
      );
    } catch (error) {
      setMessage(
        error instanceof Error
          ? error.message
          : "Handover confirmation failed"
      );
    } finally {
      setBusy(false);
    }
  }

  async function sendToFacility() {
    setBusy(true);
    setMessage("");

    try {
      await api.post(
        `/api/v1/pickups/${pickupId}/start-transit`
      );

      setTransit(true);

      setMessage(
        "Shipment status: IN TRANSIT. The selected treatment facility can now record receipt."
      );
    } catch (error) {
      setMessage(
        error instanceof Error
          ? error.message
          : "Could not start transit. Check that all route stops are collected and destination is eligible."
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="mx-auto max-w-3xl space-y-6 px-4 py-8 text-[#2b203b]">
      <h1 className="text-3xl font-bold">
        Hospital handover
      </h1>

      <p className="text-sm">
        Manual confirmation is supported without GPS.
        It is recorded as a driver declaration,
        not GPS-verified arrival.
      </p>

      <section className="space-y-4 rounded-2xl border bg-white p-6">
        <h2 className="text-xl font-bold">
          1. Manually confirm hospital arrival
        </h2>

        <label className="block text-sm font-semibold">
          Assigned pickup UUID
          <input
            className={input}
            value={pickupId}
            onChange={(e) =>
              setPickupId(e.target.value)
            }
          />
        </label>

        <label className="block text-sm font-semibold">
          Hospital handover QR reference
          <input
            className={input}
            value={qr}
            onChange={(e) => setQr(e.target.value)}
          />
        </label>

        <button
          type="button"
          className={button}
          disabled={busy}
          onClick={() => void scanQR()}
        >
          Scan hospital QR
        </button>

        <video
          ref={videoRef}
          playsInline
          muted
          className="max-h-32 w-full rounded-md"
        />

        <label className="block text-sm font-semibold">
          Arrival note (minimum 12 characters)
          <textarea
            rows={2}
            className={input}
            value={note}
            onChange={(e) =>
              setNote(e.target.value)
            }
            placeholder="State who is present and how hospital QR was obtained"
          />
        </label>

        <label className="flex items-start gap-2 text-sm">
          <input
            type="checkbox"
            checked={attested}
            onChange={(e) =>
              setAttested(e.target.checked)
            }
          />
          I attest that I am at the hospital and
          have received the hospital QR reference.
        </label>

        <button
          className={button}
          disabled={
            busy ||
            arrived ||
            !attested ||
            note.trim().length < 12 ||
            qr.trim().length < 20 ||
            !pickupId
          }
          onClick={() => void manualArrival()}
        >
          {arrived
            ? "Arrival recorded"
            : "Confirm arrival manually"}
        </button>

        <p className="text-xs text-amber-800">
          This action does not certify physical
          location using GPS. The assigned driver
          and QR are checked and the declaration
          is audited.
        </p>
      </section>

      <section className="space-y-4 rounded-2xl border bg-white p-6">
        <h2 className="text-xl font-bold">
          2. Confirm measured waste handover
        </h2>

        <label className="block text-sm font-semibold">
          Actual measured weight (kg)
          <input
            type="number"
            min="0.001"
            step="0.001"
            className={input}
            value={weight}
            onChange={(e) =>
              setWeight(e.target.value)
            }
          />
        </label>

        <label className="block text-sm font-semibold">
          Packaging condition
          <select
            className={input}
            value={packaging}
            onChange={(e) =>
              setPackaging(e.target.value)
            }
          >
            <option value="sealed">Sealed</option>
            <option value="damaged">Damaged</option>
            <option value="exception">Exception</option>
          </select>
        </label>

        <label className="block text-sm font-semibold">
          Weight / packaging exception note,
          when required
          <textarea
            rows={2}
            className={input}
            value={exception}
            onChange={(e) =>
              setException(e.target.value)
            }
          />
        </label>

        <button
          className={button}
          disabled={
            busy ||
            !arrived ||
            collected ||
            qr.trim().length < 20 ||
            !(Number(weight) > 0)
          }
          onClick={() => void confirmHandover()}
        >
          {collected
            ? "Handover recorded"
            : "Confirm handover"}
        </button>
      </section>

      <section className="space-y-3 rounded-2xl border bg-white p-6">
        <h2 className="text-xl font-bold">
          3. Send to treatment facility
        </h2>

        <p className="text-sm">
          All assigned hospital stops on this
          active route must first be collected.
        </p>

        <button
          className={button}
          disabled={
            busy ||
            !collected ||
            transit ||
            !pickupId
          }
          onClick={() => void sendToFacility()}
        >
          {transit
            ? "Shipment is in transit"
            : "Start transit / Send to facility"}
        </button>
      </section>

      {message && (
        <p
          role="status"
          className="rounded-xl border bg-[#f4f0f7] p-4 text-sm"
        >
          {message}
        </p>
      )}
    </main>
  );
}
