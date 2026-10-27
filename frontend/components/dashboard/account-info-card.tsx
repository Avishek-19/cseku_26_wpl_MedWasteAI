import { Badge } from "@/components/ui/badge";
import type { User } from "@/types/auth";
import { ROLE_LABELS } from "@/types/auth";

export function AccountInfoCard({ user }: { user: User }) {
  return (
    <div className="rounded-2xl border border-mist-deep bg-paper p-7">
      <h2 className="font-display text-lg font-semibold text-charcoal">Account</h2>
      <dl className="mt-5 grid grid-cols-1 gap-4 sm:grid-cols-2">
        <div>
          <dt className="text-[12px] text-slate-light">Full name</dt>
          <dd className="mt-0.5 text-[14px] text-charcoal">{user.full_name}</dd>
        </div>
        <div>
          <dt className="text-[12px] text-slate-light">Email</dt>
          <dd className="mt-0.5 text-[14px] text-charcoal">{user.email}</dd>
        </div>
        <div>
          <dt className="text-[12px] text-slate-light">Role</dt>
          <dd className="mt-1">
            <Badge>{ROLE_LABELS[user.role]}</Badge>
          </dd>
        </div>
        <div>
          <dt className="text-[12px] text-slate-light">Member since</dt>
          <dd className="mt-0.5 text-[14px] text-charcoal">
            {new Date(user.created_at).toLocaleDateString(undefined, {
              month: "long",
              day: "numeric",
              year: "numeric",
            })}
          </dd>
        </div>
      </dl>
    </div>
  );
}
