// Package enumerate defines the Enumerator seam (STORY-0033): a stream of
// changes plus an opaque cursor and an honest capability declaration, so the
// engine can support multiple enumeration strategies (full, delta,
// composite — the latter two are DEFERRED for v1 per
// docs/superpowers/specs/2026-08-14-go-rewrite-design.md:88) without
// restructuring.
package enumerate

import (
	"context"

	"github.com/laforcem/icloudpd/internal/asset"
)

// Cursor is opaque to the engine: persisted verbatim, never interpreted.
type Cursor []byte

// ChangeKind distinguishes an asset appearing from one being reported gone.
type ChangeKind int

const (
	Present ChangeKind = iota
	Removed
)

// Change is one observation yielded during an Enumerate call.
type Change struct {
	Kind ChangeKind
	// Asset carries the observed asset for a Present change. It is the
	// zero value for a Removed change, which only needs the key — but the
	// walking skeleton's full enumerator never yields Removed (see
	// Capabilities.ReportsRemovals), so callers in this iteration only ever
	// see Present.
	Asset asset.Asset
}

// Capabilities is the honest declaration an Enumerator makes about what its
// runs can be trusted to mean. The load-bearing contract rule (see the
// design spec's "enumeration seam" section): the engine may conclude "asset
// X is gone" only if a run completed without error AND (Exhaustive, via
// not-seen-in-sweep) OR (ReportsRemovals, via an explicit Removed change).
// Reconciliation must branch on these fields, never on a type switch or name
// check against the enumerator implementation (STORY-0034 AC-3 — that
// reconciliation logic itself is ITER-0003's job; this iteration only
// establishes the contract full's enumerator honors).
type Capabilities struct {
	ReportsRemovals bool // source explicitly tells us about deletions
	Exhaustive      bool // a completed run visited every live asset
	Resumable       bool // mid-run cursor is safe to persist
}

// Enumerator is the seam every enumeration strategy implements.
type Enumerator interface {
	Capabilities() Capabilities
	Enumerate(ctx context.Context, from Cursor, yield func(context.Context, Change) error) (Cursor, error)
}
