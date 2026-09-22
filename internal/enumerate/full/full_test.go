package full

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"net/url"
	"testing"

	"github.com/laforcem/icloudpd/internal/enumerate"
	"github.com/laforcem/icloudpd/internal/icloud/ckws"
	"github.com/laforcem/icloudpd/internal/icloud/photos"
)

// TestCapabilities is SCENARIO-0117's evidence: the full enumerator reports
// exactly {ReportsRemovals:false, Exhaustive:true, Resumable:true}
// (STORY-0033 AC-2, narrowed to full-only per the PAR scope review).
func TestCapabilities(t *testing.T) {
	e := &Enumerator{}
	got := e.Capabilities()
	want := enumerate.Capabilities{ReportsRemovals: false, Exhaustive: true, Resumable: true}
	if got != want {
		t.Fatalf("Capabilities() = %+v, want %+v", got, want)
	}
}

func cplMaster(recordName string) ckws.Record {
	filenameJSON, _ := json.Marshal(recordName + ".heic")
	itemTypeJSON, _ := json.Marshal("public.heic")
	return ckws.Record{
		RecordName: recordName,
		RecordType: "CPLMaster",
		Fields: map[string]ckws.FieldEntry{
			"filenameEnc": {Value: filenameJSON},
			"itemType":    {Value: itemTypeJSON},
		},
	}
}

func cplAsset(recordName, masterRecordName string) ckws.Record {
	masterRefJSON, _ := json.Marshal(map[string]any{"recordName": masterRecordName})
	addedJSON, _ := json.Marshal(1000)
	resJSON, _ := json.Marshal(map[string]any{"size": 42, "downloadURL": "https://example.com/" + recordName, "fileChecksum": "chk-" + recordName})
	typeJSON, _ := json.Marshal("public.heic")
	return ckws.Record{
		RecordName: recordName,
		RecordType: "CPLAsset",
		Fields: map[string]ckws.FieldEntry{
			"masterRef":           {Value: masterRefJSON},
			"addedDate":           {Value: addedJSON},
			"resOriginalRes":      {Value: resJSON},
			"resOriginalFileType": {Value: typeJSON},
		},
	}
}

// TestEnumerate_SingleAsset_CursorPersistedVerbatim is SCENARIO-0117's other
// half (STORY-0033 AC-1): Enumerate returns an updated Cursor that the
// caller persists verbatim without interpreting its contents, and yields
// exactly the assets the server returned.
func TestEnumerate_SingleAsset_CursorPersistedVerbatim(t *testing.T) {
	mux := http.NewServeMux()
	mux.HandleFunc("/database/1/com.apple.photos.cloud/production/private/records/query", func(w http.ResponseWriter, r *http.Request) {
		var req ckws.RecordsQuery
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
			t.Fatalf("server: decoding request: %v", err)
		}
		startRank := 0
		for _, f := range req.Query.FilterBy {
			if f.FieldName == "startRank" {
				if v, ok := f.FieldValue.Value.(float64); ok {
					startRank = int(v)
				}
			}
		}
		if startRank == 0 {
			json.NewEncoder(w).Encode(ckws.RecordsQueryResponse{
				Records: []ckws.Record{cplMaster("m1"), cplAsset("a1", "m1")},
			})
			return
		}
		json.NewEncoder(w).Encode(ckws.RecordsQueryResponse{})
	})
	server := httptest.NewServer(mux)
	defer server.Close()

	client := &ckws.Client{HTTP: server.Client(), ServiceRoot: server.URL, Params: url.Values{}, DatabaseType: "private"}
	e := &Enumerator{Client: client, AccountID: "acct1", ZoneName: photos.PrimarySyncZone}

	var yielded []enumerate.Change
	cursor, err := e.Enumerate(context.Background(), nil, func(_ context.Context, c enumerate.Change) error {
		yielded = append(yielded, c)
		return nil
	})
	if err != nil {
		t.Fatalf("Enumerate: %v", err)
	}
	if len(yielded) != 1 {
		t.Fatalf("got %d changes, want 1", len(yielded))
	}
	if yielded[0].Kind != enumerate.Present {
		t.Errorf("Kind = %v, want Present", yielded[0].Kind)
	}
	if yielded[0].Asset.Key.RecordName != "m1" {
		t.Errorf("RecordName = %q, want m1", yielded[0].Asset.Key.RecordName)
	}

	// The cursor is opaque to the caller: we only assert it round-trips
	// through a second Enumerate call without the engine interpreting it,
	// not that it has any particular shape.
	if len(cursor) == 0 {
		t.Fatal("expected a non-empty cursor after a completed sweep")
	}

	var replayed []enumerate.Change
	_, err = e.Enumerate(context.Background(), cursor, func(_ context.Context, c enumerate.Change) error {
		replayed = append(replayed, c)
		return nil
	})
	if err != nil {
		t.Fatalf("second Enumerate with persisted cursor: %v", err)
	}
	// Re-running from a cursor past the single asset yields nothing new —
	// proving the cursor was genuinely carried forward, not ignored.
	if len(replayed) != 0 {
		t.Fatalf("expected no new changes when resuming from a cursor past the only asset, got %d", len(replayed))
	}
}
