// Package asset defines the domain types shared across the protocol,
// enumeration, download, and store layers. It depends on nothing else in
// this module (see docs/superpowers/specs/2026-08-14-go-rewrite-design.md's
// "domain (no outward deps)" package layout rule).
package asset

// ZoneKind distinguishes an account's primary photo library from a Shared
// Photo Library zone. The walking skeleton only ever produces ZoneKindPrimary
// (STORY-0002's zone discovery is narrowed to PrimarySync; multi-zone
// discovery is STORY-0137, deferred to ITER-0001).
type ZoneKind string

const (
	ZoneKindPrimary ZoneKind = "primary"
	ZoneKindShared  ZoneKind = "shared"
)

// Key identifies an asset uniquely within an account's manifest. RecordName
// is the CPLMaster recordName (STORY-0041), not the CPLAsset recordName —
// CPLAsset recordName churns as metadata is edited, CPLMaster recordName
// does not.
type Key struct {
	AccountID  string
	ZoneKind   ZoneKind
	ZoneName   string
	RecordName string
}

// Version is one downloadable rendition of an asset (original, medium,
// thumb, ...). The walking skeleton only ever populates Original.
type Version struct {
	Size        int64
	DownloadURL string
	FileType    string
	Checksum    string // Apple's fileChecksum, base64 as provided by CloudKit
}

// Asset is one photo/video item as CloudKit represents it: a CPLMaster
// record (identity, filename, item type) joined with its current CPLAsset
// record (per-version resource pointers).
type Asset struct {
	Key      Key
	Filename string
	ItemType string // Apple's itemType UTI, e.g. "public.heic"

	// AddedDate is the CPLAsset record's addedDate, used to pick the newer
	// record when multiple CPLAsset rows exist for the same CPLMaster
	// (STORY-0140's collision policy; this iteration doesn't need to
	// exercise the tie-break itself — see EPIC-021's split note).
	AddedDateUnixMillis int64

	Original Version
}
