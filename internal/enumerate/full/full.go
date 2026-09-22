// Package full implements the day-one enumeration strategy: a startRank-paged
// sweep of one CloudKit zone. It reports Capabilities{false, true, true} —
// it never reports explicit removals, a completed run is exhaustive (visited
// every live asset), and its cursor is safe to persist mid-run.
package full

import (
	"context"
	"encoding/json"
	"fmt"

	"github.com/laforcem/icloudpd/internal/enumerate"
	"github.com/laforcem/icloudpd/internal/icloud/ckws"
	"github.com/laforcem/icloudpd/internal/icloud/photos"
)

// Enumerator sweeps one zone in a single account's private database via
// startRank paging, matching STORY-0033 AC-2's `full` capability values.
type Enumerator struct {
	Client    *ckws.Client
	AccountID string
	ZoneName  string
}

// cursorState is what full's Cursor encodes: only startRank, since a
// completed sweep has no other state worth resuming from (STORY-0136's split
// note: ranged mid-download resume is a different, deferred concern).
type cursorState struct {
	StartRank int `json:"startRank"`
}

func (e *Enumerator) Capabilities() enumerate.Capabilities {
	return enumerate.Capabilities{
		ReportsRemovals: false,
		Exhaustive:      true,
		Resumable:       true,
	}
}

func (e *Enumerator) Enumerate(ctx context.Context, from enumerate.Cursor, yield func(context.Context, enumerate.Change) error) (enumerate.Cursor, error) {
	state := cursorState{}
	if len(from) > 0 {
		if err := json.Unmarshal(from, &state); err != nil {
			return nil, fmt.Errorf("full: parsing cursor: %w", err)
		}
	}

	for {
		assets, more, err := photos.ListPage(ctx, e.Client, e.AccountID, e.ZoneName, state.StartRank)
		if err != nil {
			return nil, fmt.Errorf("full: listing page at startRank %d: %w", state.StartRank, err)
		}

		for _, a := range assets {
			if err := yield(ctx, enumerate.Change{Kind: enumerate.Present, Asset: a}); err != nil {
				return nil, fmt.Errorf("full: yield: %w", err)
			}
			state.StartRank++
		}

		if !more {
			break
		}
	}

	out, err := json.Marshal(state)
	if err != nil {
		return nil, fmt.Errorf("full: encoding cursor: %w", err)
	}
	return out, nil
}
