const STYLES: Record<string, string> = {
  covered: "bg-green-100 text-green-800",
  partly_covered: "bg-amber-100 text-amber-800",
  not_covered: "bg-red-100 text-red-800",
  unsure: "bg-gray-200 text-gray-700",
  pending: "bg-gray-100 text-gray-500",
};

export default function Badge({ decision }: { decision: string }) {
  const label = decision === "pending" ? "Pending" : decision.replace("_", " ");
  return (
    <span className={`inline-block rounded-full px-2.5 py-0.5 text-xs font-medium capitalize ${STYLES[decision] ?? STYLES.unsure}`}>
      {label}
    </span>
  );
}
