// Package photos ports the CloudKit Photos-schema query shape and record
// parsing from src/pyicloud_ipd/services/photos.py: the desiredKeys field
// set (STORY-0002), the ASCENDING startRank paged listing query, and
// CPLMaster/CPLAsset record pairing into asset.Asset.
package photos

import (
	"context"
	"encoding/base64"
	"encoding/json"
	"fmt"

	"github.com/laforcem/icloudpd/internal/asset"
	"github.com/laforcem/icloudpd/internal/icloud/ckws"
)

// DesiredKeys is copied verbatim from photos_request's desiredKeys list in
// src/pyicloud_ipd/services/photos.py — STORY-0002 AC-1 requires the Go
// client request exactly this field set.
var DesiredKeys = []string{
	"resJPEGFullWidth", "resJPEGFullHeight", "resJPEGFullFileType", "resJPEGFullFingerprint", "resJPEGFullRes",
	"resJPEGLargeWidth", "resJPEGLargeHeight", "resJPEGLargeFileType", "resJPEGLargeFingerprint", "resJPEGLargeRes",
	"resJPEGMedWidth", "resJPEGMedHeight", "resJPEGMedFileType", "resJPEGMedFingerprint", "resJPEGMedRes",
	"resJPEGThumbWidth", "resJPEGThumbHeight", "resJPEGThumbFileType", "resJPEGThumbFingerprint", "resJPEGThumbRes",
	"resVidFullWidth", "resVidFullHeight", "resVidFullFileType", "resVidFullFingerprint", "resVidFullRes",
	"resVidMedWidth", "resVidMedHeight", "resVidMedFileType", "resVidMedFingerprint", "resVidMedRes",
	"resVidSmallWidth", "resVidSmallHeight", "resVidSmallFileType", "resVidSmallFingerprint", "resVidSmallRes",
	"resSidecarWidth", "resSidecarHeight", "resSidecarFileType", "resSidecarFingerprint", "resSidecarRes",
	"itemType", "dataClassType", "filenameEnc", "originalOrientation",
	"resOriginalWidth", "resOriginalHeight", "resOriginalFileType", "resOriginalFingerprint", "resOriginalRes",
	"resOriginalAltWidth", "resOriginalAltHeight", "resOriginalAltFileType", "resOriginalAltFingerprint", "resOriginalAltRes",
	"resOriginalVidComplWidth", "resOriginalVidComplHeight", "resOriginalVidComplFileType", "resOriginalVidComplFingerprint", "resOriginalVidComplRes",
	"isDeleted", "isExpunged", "dateExpunged", "remappedRef", "recordName", "recordType", "recordChangeTag",
	"masterRef", "adjustmentRenderType", "assetDate", "addedDate", "isFavorite", "isHidden", "orientation",
	"duration", "assetSubtype", "assetSubtypeV2", "assetHDRType", "burstFlags", "burstFlagsExt", "burstId",
	"captionEnc", "locationEnc", "locationV2Enc", "locationLatitude", "locationLongitude", "adjustmentType",
	"timeZoneOffset", "vidComplDurValue", "vidComplDurScale", "vidComplDispValue", "vidComplDispScale",
	"keywordsEnc", "extendedDescEnc", "adjustedMediaMetaDataEnc", "adjustmentSimpleDataEnc",
	"vidComplVisibilityState", "customRenderedValue", "containerId", "itemId", "position", "isKeyAsset",
}

// WholeCollectionListType is PhotoLibrary.WHOLE_COLLECTION's list_type: the
// query that lists every non-hidden, non-deleted asset in a zone.
const WholeCollectionListType = "CPLAssetAndMasterByAssetDateWithoutHiddenOrDeleted"

const PrimarySyncZone = "PrimarySync"

// PageSize mirrors PhotoAlbum's default page_size; resultsLimit is 2x this,
// matching the reference client (CPLMaster+CPLAsset pairs count as two
// records per logical asset).
const PageSize = 100

// ListPage runs one records/query call for the WHOLE_COLLECTION query at the
// given startRank offset within zoneName, and returns the resulting assets
// plus whether more pages likely remain (fewer raw records than requested
// means the last page was reached).
func ListPage(ctx context.Context, client *ckws.Client, accountID, zoneName string, startRank int) (assets []asset.Asset, morePages bool, err error) {
	resp, err := client.RecordsQuery(ctx, ckws.RecordsQuery{
		Query: ckws.QuerySpec{
			RecordType: WholeCollectionListType,
			FilterBy: []ckws.QueryFilter{
				{FieldName: "startRank", Comparator: "EQUALS", FieldValue: ckws.FieldValue{Type: "INT64", Value: startRank}},
				{FieldName: "direction", Comparator: "EQUALS", FieldValue: ckws.FieldValue{Type: "STRING", Value: "ASCENDING"}},
			},
		},
		ZoneID:       ckws.ZoneID{ZoneName: zoneName},
		ResultsLimit: PageSize * 2,
		DesiredKeys:  DesiredKeys,
	})
	if err != nil {
		return nil, false, fmt.Errorf("photos: listing page at startRank %d: %w", startRank, err)
	}

	assets, err = pairRecords(resp.Records, accountID, zoneName)
	if err != nil {
		return nil, false, err
	}
	return assets, len(resp.Records) >= PageSize*2, nil
}

// pairRecords joins CPLMaster and CPLAsset records by masterRef, applying
// the newest-addedDate collision policy (STORY-0041/STORY-0140) when
// multiple CPLAsset records reference the same CPLMaster.
func pairRecords(records []ckws.Record, accountID, zoneName string) ([]asset.Asset, error) {
	masters := make([]ckws.Record, 0, len(records))
	assetByMaster := make(map[string]ckws.Record)

	for _, rec := range records {
		switch rec.RecordType {
		case "CPLMaster":
			masters = append(masters, rec)
		case "CPLAsset":
			masterID, err := masterRefRecordName(rec)
			if err != nil {
				return nil, fmt.Errorf("photos: CPLAsset %s: %w", rec.RecordName, err)
			}
			existing, ok := assetByMaster[masterID]
			if !ok {
				assetByMaster[masterID] = rec
				continue
			}
			kept, err := pickNewerAssetRecord(existing, rec)
			if err != nil {
				return nil, err
			}
			assetByMaster[masterID] = kept
		}
	}

	out := make([]asset.Asset, 0, len(masters))
	for _, master := range masters {
		assetRec, ok := assetByMaster[master.RecordName]
		if !ok {
			continue // a master with no matching CPLAsset yet; skip rather than fail the page
		}
		a, err := buildAsset(master, assetRec, accountID, zoneName)
		if err != nil {
			return nil, err
		}
		out = append(out, a)
	}
	return out, nil
}

func masterRefRecordName(cplAsset ckws.Record) (string, error) {
	entry, ok := cplAsset.Fields["masterRef"]
	if !ok {
		return "", fmt.Errorf("missing masterRef field")
	}
	var value struct {
		RecordName string `json:"recordName"`
	}
	if err := json.Unmarshal(entry.Value, &value); err != nil {
		return "", fmt.Errorf("parsing masterRef: %w", err)
	}
	if value.RecordName == "" {
		return "", fmt.Errorf("masterRef missing recordName")
	}
	return value.RecordName, nil
}

// pickNewerAssetRecord ports _pick_newer_asset_record: prefer the record
// with the later addedDate; a record missing addedDate is older than one
// that has it.
func pickNewerAssetRecord(a, b ckws.Record) (ckws.Record, error) {
	aAdded, aHas := addedDateMillis(a)
	bAdded, bHas := addedDateMillis(b)
	switch {
	case !bHas:
		return a, nil
	case !aHas:
		return b, nil
	case bAdded > aAdded:
		return b, nil
	default:
		return a, nil
	}
}

func addedDateMillis(rec ckws.Record) (int64, bool) {
	entry, ok := rec.Fields["addedDate"]
	if !ok {
		return 0, false
	}
	var v float64
	if err := json.Unmarshal(entry.Value, &v); err != nil {
		return 0, false
	}
	return int64(v), true
}

func fieldString(fields map[string]ckws.FieldEntry, key string) (string, error) {
	entry, ok := fields[key]
	if !ok {
		return "", fmt.Errorf("missing field %q", key)
	}
	var s string
	if err := json.Unmarshal(entry.Value, &s); err != nil {
		return "", fmt.Errorf("field %q not a string: %w", key, err)
	}
	return s, nil
}

// resOriginalValue is CloudKit's ASSETID-shaped field for resOriginalRes:
// {"size": N, "downloadURL": "...", "fileChecksum": "..."}.
type resOriginalValue struct {
	Size         int64  `json:"size"`
	DownloadURL  string `json:"downloadURL"`
	FileChecksum string `json:"fileChecksum"`
}

// decodeFilename ports PhotoAsset.calculate_filename: filenameEnc is a
// {"type": ..., "value": ...} field whose value is either a plain string
// (type STRING) or base64-encoded bytes (type ENCRYPTED_BYTES) — decoding
// it unconditionally as a plain string, as an earlier version of this
// function did, produces garbled base64 filenames on disk whenever Apple
// sends the encrypted-bytes form. A missing field returns "" (the caller's
// job to fall back to a fingerprint-based name, matching the reference
// client's filename_with_fallback — not implemented in this walking
// skeleton, which only needs a stable, correct name for one file).
func decodeFilename(entry ckws.FieldEntry) (string, error) {
	if entry.Type == "" && len(entry.Value) == 0 {
		return "", nil // field absent
	}
	var value string
	if err := json.Unmarshal(entry.Value, &value); err != nil {
		return "", fmt.Errorf("parsing filenameEnc value: %w", err)
	}
	switch entry.Type {
	case "", "STRING":
		return value, nil
	case "ENCRYPTED_BYTES":
		decoded, err := base64.StdEncoding.DecodeString(value)
		if err != nil {
			return "", fmt.Errorf("base64-decoding filenameEnc: %w", err)
		}
		return string(decoded), nil
	default:
		return "", fmt.Errorf("unsupported filenameEnc type %q", entry.Type)
	}
}

func buildAsset(master, assetRec ckws.Record, accountID, zoneName string) (asset.Asset, error) {
	itemType, _ := fieldString(master.Fields, "itemType")

	filename, err := decodeFilename(master.Fields["filenameEnc"])
	if err != nil {
		return asset.Asset{}, fmt.Errorf("asset %s: %w", master.RecordName, err)
	}

	addedMillis, _ := addedDateMillis(assetRec)

	original, err := extractVersion(assetRec, master, "resOriginal")
	if err != nil {
		return asset.Asset{}, fmt.Errorf("asset %s: %w", master.RecordName, err)
	}

	return asset.Asset{
		Key: asset.Key{
			AccountID:  accountID,
			ZoneKind:   asset.ZoneKindPrimary,
			ZoneName:   zoneName,
			RecordName: master.RecordName,
		},
		Filename:            filename,
		ItemType:            itemType,
		AddedDateUnixMillis: addedMillis,
		Original:            original,
	}, nil
}

// extractVersion mirrors PhotoAsset.versions: prefer the CPLAsset record's
// fields, fall back to the CPLMaster record's fields for the same prefix.
func extractVersion(assetRec, master ckws.Record, prefix string) (asset.Version, error) {
	resKey := prefix + "Res"
	typeKey := prefix + "FileType"

	fields := assetRec.Fields
	if _, ok := fields[resKey]; !ok {
		fields = master.Fields
	}

	resEntry, ok := fields[resKey]
	if !ok {
		return asset.Version{}, fmt.Errorf("expected %s, but missing it", resKey)
	}
	var res resOriginalValue
	if err := json.Unmarshal(resEntry.Value, &res); err != nil {
		return asset.Version{}, fmt.Errorf("parsing %s: %w", resKey, err)
	}

	typeEntry, ok := fields[typeKey]
	if !ok {
		return asset.Version{}, fmt.Errorf("expected %s, but missing it", typeKey)
	}
	var fileType string
	if err := json.Unmarshal(typeEntry.Value, &fileType); err != nil {
		return asset.Version{}, fmt.Errorf("parsing %s: %w", typeKey, err)
	}

	return asset.Version{
		Size:        res.Size,
		DownloadURL: res.DownloadURL,
		FileType:    fileType,
		Checksum:    res.FileChecksum,
	}, nil
}
