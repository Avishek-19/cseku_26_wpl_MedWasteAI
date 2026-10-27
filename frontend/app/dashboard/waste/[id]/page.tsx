import { WasteDetail } from "@/components/dashboard/waste/waste-detail";

export default async function WasteRecordPage(
  props: { params: Promise<{ id: string }> }
) {
  const { id } = await props.params;
  return <WasteDetail recordId={id} />;
}
