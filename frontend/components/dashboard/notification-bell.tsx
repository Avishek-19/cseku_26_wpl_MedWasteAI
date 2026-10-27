"use client";

import { Bell,CheckCheck } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect,useRef,useState } from "react";

import { api } from "@/lib/api";
import { cn } from "@/lib/utils";
import type { NotificationListResponse } from "@/types/waste";

export function NotificationBell() {
  const router = useRouter();
  const [data, setData] = useState<NotificationListResponse | null>(null);
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  const load = () => {
    api.get<NotificationListResponse>("/api/v1/notifications").then(setData);
  };

  useEffect(() => {
    load();
    const interval = setInterval(load, 30000);
    return () => clearInterval(interval);
  }, []);

  useEffect(() => {
    const onClickOutside = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onClickOutside);
    return () => document.removeEventListener("mousedown", onClickOutside);
  }, []);

  const openNotification = async (id: string, wasteRecordId: string | null) => {
    await api.post(`/api/v1/notifications/${id}/read`);
    load();
    setOpen(false);
    if (wasteRecordId) router.push(`/dashboard/waste/${wasteRecordId}`);
  };

  const markAllRead = async () => {
    await api.post("/api/v1/notifications/read-all");
    load();
  };

  const unread = data?.unread_count ?? 0;

  return (
    <div className="relative" ref={ref}>
      <button
        onClick={() => setOpen((v) => !v)}
        className="relative flex h-9 w-9 items-center justify-center rounded-lg text-slate transition-colors hover:bg-mist hover:text-charcoal"
        aria-label="Notifications"
      >
        <Bell size={16} />
        {unread > 0 && (
          <span className="absolute right-1.5 top-1.5 flex h-2 w-2 rounded-full bg-signal-rust" />
        )}
      </button>

      {open && (
        <div className="fixed inset-x-4 top-20 z-50 w-auto sm:absolute sm:inset-x-auto sm:right-0 sm:top-11 sm:w-80 rounded-xl border border-mist-deep bg-paper shadow-[0_20px_50px_-20px_rgba(14,59,46,0.3)]">
          <div className="flex items-center justify-between border-b border-mist-deep px-4 py-3">
            <p className="text-[13px] font-medium text-charcoal">Notifications</p>
            {unread > 0 && (
              <button
                onClick={markAllRead}
                className="flex items-center gap-1 text-[12px] text-emerald hover:underline"
              >
                <CheckCheck size={12} /> Mark all read
              </button>
            )}
          </div>

          <div className="max-h-80 overflow-y-auto">
            {!data || data.items.length === 0 ? (
              <p className="px-4 py-8 text-center text-[13px] text-slate-light">
                Nothing yet.
              </p>
            ) : (
              data.items.map((n) => (
                <button
                  key={n.id}
                  onClick={() => openNotification(n.id, n.waste_record_id)}
                  className={cn(
                    "block w-full border-b border-mist-deep px-4 py-3 text-left transition-colors last:border-0 hover:bg-mist",
                    !n.is_read && "bg-signal-emerald-bg/40"
                  )}
                >
                  <p className="text-[13px] font-medium text-charcoal">{n.title}</p>
                  <p className="mt-0.5 line-clamp-2 text-[12px] text-slate">{n.body}</p>
                  <p className="mt-1 text-[11px] text-slate-light">
                    {new Date(n.created_at).toLocaleString()}
                  </p>
                </button>
              ))
            )}
          </div>
        </div>
      )}
    </div>
  );
}
