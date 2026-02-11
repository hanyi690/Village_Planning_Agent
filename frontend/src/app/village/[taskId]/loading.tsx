/**
 * Loading page for village task
 * Displayed while the task data is being loaded
 */
export default function Loading() {
  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-50">
      <div className="text-center">
        <div className="inline-block animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600 mb-4" />
        <p className="text-gray-600">加载任务数据...</p>
      </div>
    </div>
  );
}
