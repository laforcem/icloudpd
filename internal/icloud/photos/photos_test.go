package photos

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"net/url"
	"testing"

	"github.com/laforcem/icloudpd/internal/icloud/ckws"
)

func cplMaster(recordName, filename, itemType string) ckws.Record {
	filenameJSON, _ := json.Marshal(filename)
	itemTypeJSON, _ := json.Marshal(itemType)
	return ckws.Record{
		RecordName: recordName,
		RecordType: "CPLMaster",
		Fields: map[string]ckws.FieldEntry{
			"filenameEnc": {Type: "STRING", Value: filenameJSON},
			"itemType":    {Type: "STRING", Value: itemTypeJSON},
		},
	}
}

func cplAsset(recordName, masterRecordName string, addedDateMillis int64, checksum string) ckws.Record {
	masterRefJSON, _ := json.Marshal(map[string]any{"recordName": masterRecordName})
	addedJSON, _ := json.Marshal(addedDateMillis)
	resOriginalJSON, _ := json.Marshal(map[string]any{
		"size":         12345,
		"downloadURL":  "https://example.com/download/" + recordName,
		"fileChecksum": checksum,
	})
	fileTypeJSON, _ := json.Marshal("public.heic")
	return ckws.Record{
		RecordName: recordName,
		RecordType: "CPLAsset",
		Fields: map[string]ckws.FieldEntry{
			"masterRef":           {Type: "REFERENCE", Value: masterRefJSON},
			"addedDate":           {Type: "INT64", Value: addedJSON},
			"resOriginalRes":      {Type: "ASSETID", Value: resOriginalJSON},
			"resOriginalFileType": {Type: "STRING", Value: fileTypeJSON},
		},
	}
}

// TestListPage_DesiredKeys is STORY-0002 AC-1's evidence: the Go client
// requests exactly the same desiredKeys field set as the Python reference
// client's photos_request.
func TestListPage_DesiredKeys(t *testing.T) {
	var captured ckws.RecordsQuery
	mux := http.NewServeMux()
	mux.HandleFunc("/database/1/com.apple.photos.cloud/production/private/records/query", func(w http.ResponseWriter, r *http.Request) {
		if err := json.NewDecoder(r.Body).Decode(&captured); err != nil {
			t.Fatalf("decoding request: %v", err)
		}
		json.NewEncoder(w).Encode(ckws.RecordsQueryResponse{})
	})
	server := httptest.NewServer(mux)
	defer server.Close()

	client := &ckws.Client{HTTP: server.Client(), ServiceRoot: server.URL, Params: url.Values{}, DatabaseType: "private"}
	_, _, err := ListPage(context.Background(), client, "acct1", PrimarySyncZone, 0)
	if err != nil {
		t.Fatalf("ListPage: %v", err)
	}

	if len(captured.DesiredKeys) != len(DesiredKeys) {
		t.Fatalf("desiredKeys length = %d, want %d", len(captured.DesiredKeys), len(DesiredKeys))
	}
	for i, key := range DesiredKeys {
		if captured.DesiredKeys[i] != key {
			t.Errorf("desiredKeys[%d] = %q, want %q", i, captured.DesiredKeys[i], key)
		}
	}
	if captured.Query.RecordType != WholeCollectionListType {
		t.Errorf("recordType = %q, want %q", captured.Query.RecordType, WholeCollectionListType)
	}
	if captured.ZoneID.ZoneName != PrimarySyncZone {
		t.Errorf("zoneID.zoneName = %q, want %q", captured.ZoneID.ZoneName, PrimarySyncZone)
	}
}

func TestListPage_PairsSingleAsset(t *testing.T) {
	records := []ckws.Record{
		cplMaster("master-1", "photo.heic", "public.heic"),
		cplAsset("asset-1", "master-1", 1000, "checksum-abc"),
	}
	mux := http.NewServeMux()
	mux.HandleFunc("/database/1/com.apple.photos.cloud/production/private/records/query", func(w http.ResponseWriter, r *http.Request) {
		json.NewEncoder(w).Encode(ckws.RecordsQueryResponse{Records: records})
	})
	server := httptest.NewServer(mux)
	defer server.Close()

	client := &ckws.Client{HTTP: server.Client(), ServiceRoot: server.URL, Params: url.Values{}, DatabaseType: "private"}
	assets, more, err := ListPage(context.Background(), client, "acct1", PrimarySyncZone, 0)
	if err != nil {
		t.Fatalf("ListPage: %v", err)
	}
	if more {
		t.Error("expected morePages = false for a short page")
	}
	if len(assets) != 1 {
		t.Fatalf("got %d assets, want 1", len(assets))
	}
	a := assets[0]
	if a.Key.RecordName != "master-1" {
		t.Errorf("RecordName = %q, want master-1 (CPLMaster recordName, not CPLAsset)", a.Key.RecordName)
	}
	if a.Filename != "photo.heic" {
		t.Errorf("Filename = %q, want photo.heic", a.Filename)
	}
	if a.Original.Checksum != "checksum-abc" {
		t.Errorf("Checksum = %q, want checksum-abc", a.Original.Checksum)
	}
	if a.Original.Size != 12345 {
		t.Errorf("Size = %d, want 12345", a.Original.Size)
	}
}

// TestPairRecords_DuplicateCollapsesByNewestAddedDate is SCENARIO-0119's
// evidence (STORY-0041 AC-1): two CPLAsset records sharing one CPLMaster
// recordName resolve to a single asset, keyed on the CPLMaster recordName.
func TestPairRecords_DuplicateCollapsesByNewestAddedDate(t *testing.T) {
	records := []ckws.Record{
		cplMaster("master-1", "photo.heic", "public.heic"),
		cplAsset("asset-old", "master-1", 1000, "checksum-old"),
		cplAsset("asset-new", "master-1", 2000, "checksum-new"),
	}

	assets, err := pairRecords(records, "acct1", PrimarySyncZone)
	if err != nil {
		t.Fatalf("pairRecords: %v", err)
	}
	if len(assets) != 1 {
		t.Fatalf("got %d assets, want exactly 1 (duplicates must collapse)", len(assets))
	}
	if assets[0].Key.RecordName != "master-1" {
		t.Errorf("RecordName = %q, want master-1", assets[0].Key.RecordName)
	}
	if assets[0].Original.Checksum != "checksum-new" {
		t.Errorf("checksum = %q, want checksum-new (newer addedDate must win)", assets[0].Original.Checksum)
	}
}

func TestPairRecords_MissingAddedDateLosesToPresent(t *testing.T) {
	withDate := cplAsset("asset-with-date", "master-1", 500, "checksum-has-date")
	noDate := cplAsset("asset-no-date", "master-1", 0, "checksum-no-date")
	delete(noDate.Fields, "addedDate")

	records := []ckws.Record{
		cplMaster("master-1", "photo.heic", "public.heic"),
		noDate,
		withDate,
	}
	assets, err := pairRecords(records, "acct1", PrimarySyncZone)
	if err != nil {
		t.Fatalf("pairRecords: %v", err)
	}
	if len(assets) != 1 {
		t.Fatalf("got %d assets, want 1", len(assets))
	}
	if assets[0].Original.Checksum != "checksum-has-date" {
		t.Errorf("checksum = %q, want checksum-has-date (a record with addedDate beats one without)", assets[0].Original.Checksum)
	}
}
