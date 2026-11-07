import { ApiError } from "@/services/platform";

/** A short, human title for a failed API call. Plain module (not "use client")
 *  so server components can use it too. */
export function errorTitle(error: Error): string {
  if (error instanceof ApiError) {
    if (error.status === 0) return "Can't reach the server";
    if (error.status === 503) return "Project data is unavailable right now";
    if (error.status === 404) return "Not found";
  }
  return "Something went wrong";
}
