/** Security rule: ordinary browsing must never ask for hidden entries. */
export function effectiveReviewStatus(reviewMode: boolean, selectedStatus: string): string {
  return reviewMode ? selectedStatus : 'visible';
}
