import ReaderPageClient from "./reader-page-client";

export default async function ReaderPage({ params }: { params: Promise<{ paperId: string }> }) {
  const { paperId } = await params;
  return <ReaderPageClient paperId={paperId} />;
}
