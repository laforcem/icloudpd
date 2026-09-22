// Package ckws implements the CloudKit web-service transport: records/query
// and zones/list POST requests against setup.icloud.com's photos database
// endpoint. It owns HTTP framing only; internal/icloud/photos owns the
// query shapes and record parsing specific to the Photos schema.
package ckws

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/url"
)

// Client issues CloudKit records/query and zones/list requests against one
// database (private or shared) for one account.
type Client struct {
	HTTP         *http.Client
	ServiceRoot  string     // e.g. https://p12-ckdatabasews.icloud.com:443
	Params       url.Values // clientBuildNumber, clientMasteringNumber, clientId, dsid
	DatabaseType string     // "private" or "shared" — walking skeleton only uses "private"
}

// These match base.py's session-wide headers (base.py:168-174), which it
// sets once at PyiCloudService.__init__ and applies to every request,
// including CloudKit calls. Apple's server rejects ckws requests missing
// them with a generic 401 ("no auth method found") even when the session
// cookies are otherwise valid — cookies alone aren't sufficient.
const (
	homeEndpoint = "https://www.icloud.com"
	userAgent    = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36"
)

func (c *Client) setCommonHeaders(req *http.Request) {
	req.Header.Set("Origin", homeEndpoint)
	req.Header.Set("Referer", homeEndpoint+"/")
	req.Header.Set("User-Agent", userAgent)
}

// ServiceEndpoint mirrors base.py's PhotosService.get_service_endpoint.
func (c *Client) serviceEndpoint() string {
	return fmt.Sprintf("%s/database/1/com.apple.photos.cloud/production/%s", c.ServiceRoot, c.DatabaseType)
}

// ZoneID identifies a CloudKit zone within a database.
type ZoneID struct {
	ZoneName string `json:"zoneName"`
	OwnerID  string `json:"zoneOwnerRecordId,omitempty"`
}

// RecordsQuery is the request body for POST .../records/query.
type RecordsQuery struct {
	Query        QuerySpec `json:"query"`
	ZoneID       ZoneID    `json:"zoneID"`
	ResultsLimit int       `json:"resultsLimit,omitempty"`
	DesiredKeys  []string  `json:"desiredKeys,omitempty"`
}

type QuerySpec struct {
	RecordType string        `json:"recordType"`
	FilterBy   []QueryFilter `json:"filterBy,omitempty"`
}

type QueryFilter struct {
	FieldName  string     `json:"fieldName"`
	Comparator string     `json:"comparator"`
	FieldValue FieldValue `json:"fieldValue"`
}

type FieldValue struct {
	Type  string `json:"type"`
	Value any    `json:"value"`
}

// RecordsQueryResponse is the subset of CloudKit's records/query response
// this walking skeleton needs.
type RecordsQueryResponse struct {
	Records []Record `json:"records"`
}

type Record struct {
	RecordName string                `json:"recordName"`
	RecordType string                `json:"recordType"`
	Fields     map[string]FieldEntry `json:"fields"`
}

type FieldEntry struct {
	Type  string          `json:"type"`
	Value json.RawMessage `json:"value"`
}

// RecordsQuery issues one records/query POST and decodes the response.
func (c *Client) RecordsQuery(ctx context.Context, q RecordsQuery) (*RecordsQueryResponse, error) {
	body, err := json.Marshal(q)
	if err != nil {
		return nil, fmt.Errorf("ckws: marshalling records/query request: %w", err)
	}

	u := c.serviceEndpoint() + "/records/query?" + c.Params.Encode()
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, u, bytes.NewReader(body))
	if err != nil {
		return nil, err
	}
	req.Header.Set("Content-Type", "text/plain")
	c.setCommonHeaders(req)

	resp, err := c.HTTP.Do(req)
	if err != nil {
		return nil, fmt.Errorf("ckws: records/query request: %w", err)
	}
	defer resp.Body.Close()

	respBody, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil, fmt.Errorf("ckws: reading records/query response: %w", err)
	}
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		return nil, fmt.Errorf("ckws: records/query returned status %d: %s", resp.StatusCode, respBody)
	}

	var out RecordsQueryResponse
	if err := json.Unmarshal(respBody, &out); err != nil {
		return nil, fmt.Errorf("ckws: decoding records/query response: %w", err)
	}
	return &out, nil
}

// ZonesListResponse is zones/list's response shape.
type ZonesListResponse struct {
	Zones []ZoneListEntry `json:"zones"`
}

type ZoneListEntry struct {
	ZoneID  ZoneID `json:"zoneID"`
	Deleted bool   `json:"deleted"`
}

// ZonesList issues one zones/list POST and decodes the response.
func (c *Client) ZonesList(ctx context.Context) (*ZonesListResponse, error) {
	u := c.serviceEndpoint() + "/zones/list?" + c.Params.Encode()
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, u, bytes.NewReader([]byte("{}")))
	if err != nil {
		return nil, err
	}
	req.Header.Set("Content-Type", "text/plain")
	c.setCommonHeaders(req)

	resp, err := c.HTTP.Do(req)
	if err != nil {
		return nil, fmt.Errorf("ckws: zones/list request: %w", err)
	}
	defer resp.Body.Close()

	respBody, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil, fmt.Errorf("ckws: reading zones/list response: %w", err)
	}
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		return nil, fmt.Errorf("ckws: zones/list returned status %d: %s", resp.StatusCode, respBody)
	}

	var out ZonesListResponse
	if err := json.Unmarshal(respBody, &out); err != nil {
		return nil, fmt.Errorf("ckws: decoding zones/list response: %w", err)
	}
	return &out, nil
}
