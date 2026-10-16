// Session-owned immutable content interning. The same bytes uploaded in different
// turns share one string while the session is alive. Nothing persists outside
// the Console's browser-memory lifecycle.
export class MediaDataRegistry {
  private readonly values = new Map<string, string>();

  intern<T extends { data: string }>(item: T): T {
    let canonical = this.values.get(item.data);
    if (canonical === undefined) {
      canonical = item.data;
      this.values.set(canonical, canonical);
    }
    return { ...item, data: canonical };
  }

  get uniqueCount(): number { return this.values.size; }

  clear(): void { this.values.clear(); }
}
