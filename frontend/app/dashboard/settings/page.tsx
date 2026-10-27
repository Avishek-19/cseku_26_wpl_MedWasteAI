import { ChangePasswordForm } from "@/components/dashboard/change-password-form";
import { UpdateNameForm } from "@/components/dashboard/update-name-form";

export default function SettingsPage() {
  return (
    <div className="mx-auto max-w-3xl space-y-6">
      <div>
        <h1 className="font-display text-2xl font-semibold text-charcoal">Settings</h1>
        <p className="mt-1.5 text-[14px] text-slate">
          Update your account details and password.
        </p>
      </div>

      <UpdateNameForm />
      <ChangePasswordForm />
    </div>
  );
}
