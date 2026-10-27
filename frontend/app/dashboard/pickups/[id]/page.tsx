import { PickupDetail } from "@/components/dashboard/pickups/pickup-detail";

export default async function PickupPage(props: { params: Promise<{ id: string }> }) {
  const { id } = await props.params;
  return <PickupDetail pickupId={id} />;
}
