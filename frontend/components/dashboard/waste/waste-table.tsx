"use client";

import { ChevronLeft,ChevronRight,PackageSearch,Plus,Search } from "lucide-react";
import Link from "next/link";
import { useRouter,useSearchParams } from "next/navigation";
import { useEffect,useState } from "react";

import { WasteStatusBadge } from "@/components/dashboard/waste/status-badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { api } from "@/lib/api";
import type { WasteCategory,WasteRecordListResponse,WasteStatus } from "@/types/waste";
import { WASTE_STATUS_LABELS } from "@/types/waste";

const PAGE_SIZE = 10;

export function WasteTable() {
  const router = useRouter();
  const searchParams = useSearchParams();

  const page = Number(searchParams.get("page") ?? "1");
  const search = searchParams.get("search") ?? "";
  const status = (searchParams.get("status") ?? "") as WasteStatus | "";
  const categoryId = searchParams.get("category_id") ?? "";

  const [searchInput, setSearchInput] = useState(search);
  const [categories, setCategories] = useState<WasteCategory[]>([]);
  const [data, setData] = useState<WasteRecordListResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    void api.get<WasteCategory[]>("/api/v1/waste/categories").then(setCategories)
      .catch((err) => setError(err instanceof Error ? err.message : "Could not load waste categories."));
  }, []);

  useEffect(() => {
    // Refetch whenever the page/search/filters change — driven by the URL,
    // not local component state, so there's no simpler render-time alternative.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setLoading(true);
    const params = new URLSearchParams({
      page: String(page),
      page_size: String(PAGE_SIZE),
    });
    if (search) params.set("search", search);
    if (status) params.set("status", status);
    if (categoryId) params.set("category_id", categoryId);

    api
      .get<WasteRecordListResponse>(`/api/v1/waste?${params.toString()}`)
      .then((result) => {setData(result); setError(null);})
      .catch((err) => setError(err instanceof Error ? err.message : "Could not load waste records."))
      .finally(() => setLoading(false));
  }, [page, search, status, categoryId]);

  const updateParams = (updates: Record<string, string>) => {
    const params = new URLSearchParams(searchParams.toString());
    Object.entries(updates).forEach(([key, value]) => {
      if (value) params.set(key, value);
      else params.delete(key);
    });
    if (!("page" in updates)) params.set("page", "1");
    router.push(`/dashboard/waste?${params.toString()}`);
  };

  return (
    <div>
      <div className="flex flex-col justify-between gap-4 sm:flex-row sm:items-center">
        <div>
          <h1 className="font-display text-2xl font-semibold text-charcoal">Waste</h1>
          <p className="mt-1.5 text-[14px] text-slate">
            Every batch you&apos;ve reported, searchable and filterable.
          </p>
        </div>
        <Button asChild>
          <Link href="/dashboard/waste/new">
            <Plus size={16} /> Report waste
          </Link>
        </Button>
      </div>

      <div className="mt-6 flex flex-col gap-3 sm:flex-row">
        <form
          className="relative flex-1"
          onSubmit={(e) => {
            e.preventDefault();
            updateParams({ search: searchInput });
          }}
        >
          <Search
            size={15}
            className="pointer-events-none absolute left-3.5 top-1/2 -translate-y-1/2 text-slate-light"
          />
          <Input
            value={searchInput}
            onChange={(e) => setSearchInput(e.target.value)}
            placeholder="Search by waste ID or description"
            className="pl-9"
          />
        </form>

        <Select
          value={status}
          onChange={(e) => updateParams({ status: e.target.value })}
          className="sm:w-52"
        >
          <option value="">All statuses</option>
          {Object.entries(WASTE_STATUS_LABELS).map(([value, label]) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </Select>

        <Select
          value={categoryId}
          onChange={(e) => updateParams({ category_id: e.target.value })}
          className="sm:w-52"
        >
          <option value="">All categories</option>
          {categories.map((c) => (
            <option key={c.id} value={c.id}>
              {c.name}
            </option>
          ))}
        </Select>
      </div>

      {error && <p role="alert" className="mt-4 rounded-lg border border-signal-rust/20 bg-signal-rust-bg p-3 text-sm text-signal-rust">{error} <Button variant="outline" size="sm" onClick={() => window.location.reload()}>Retry</Button></p>}
      <div className="mt-6 overflow-hidden rounded-2xl border border-mist-deep bg-paper">
        {loading ? (
          <div className="p-10 text-center text-[14px] text-slate">Loading…</div>
        ) : !data || data.items.length === 0 ? (
          <div className="flex flex-col items-center gap-3 p-14 text-center">
            <PackageSearch size={28} className="text-slate-light" strokeWidth={1.5} />
            <p className="text-[14px] text-slate">
              {search || status || categoryId
                ? "No waste records match your filters."
                : "No waste reported yet."}
            </p>
            {!search && !status && !categoryId && (
              <Button size="sm" variant="outline" asChild>
                <Link href="/dashboard/waste/new">Report your first batch</Link>
              </Button>
            )}
          </div>
        ) : (
          <table className="w-full text-left text-[13.5px]">
            <thead>
              <tr className="border-b border-mist-deep bg-mist/50 text-[11.5px] uppercase tracking-wide text-slate-light">
                <th className="px-5 py-3 font-medium">Waste ID</th>
                <th className="px-5 py-3 font-medium">Category</th>
                <th className="px-5 py-3 font-medium">Quantity</th>
                <th className="px-5 py-3 font-medium">Generated</th>
                <th className="px-5 py-3 font-medium">Status</th>
              </tr>
            </thead>
            <tbody>
              {data.items.map((record) => (
                <tr
                  key={record.id}
                  className="cursor-pointer border-b border-mist-deep last:border-0 hover:bg-mist/40"
                  onClick={() => router.push(`/dashboard/waste/${record.id}`)}
                >
                  <td className="px-5 py-3 font-data text-charcoal">{record.waste_code}</td>
                  <td className="px-5 py-3 text-charcoal">{record.category.name}</td>
                  <td className="px-5 py-3 text-charcoal">
                    {record.quantity} {record.unit}
                  </td>
                  <td className="px-5 py-3 text-slate">
                    {new Date(record.generated_at).toLocaleDateString()}
                  </td>
                  <td className="px-5 py-3">
                    <WasteStatusBadge status={record.status} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {data && data.total_pages > 1 && (
        <div className="mt-4 flex items-center justify-between text-[13px] text-slate">
          <span>
            Page {data.page} of {data.total_pages} · {data.total} total
          </span>
          <div className="flex gap-2">
            <Button
              size="sm"
              variant="outline"
              disabled={page <= 1}
              onClick={() => updateParams({ page: String(page - 1) })}
            >
              <ChevronLeft size={14} /> Prev
            </Button>
            <Button
              size="sm"
              variant="outline"
              disabled={page >= data.total_pages}
              onClick={() => updateParams({ page: String(page + 1) })}
            >
              Next <ChevronRight size={14} />
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
