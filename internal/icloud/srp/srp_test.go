package srp

import (
	"encoding/hex"
	"encoding/json"
	"os"
	"testing"
)

// vector mirrors testdata/vectors.json, generated from the reference Python
// `srp` library (the same library pyicloud_ipd uses against live Apple
// servers) with a fixed ephemeral secret so the handshake is deterministic.
// Each vector was produced by running a full client+server round trip
// through that reference implementation and asserting the server accepted
// the client's proof — see the generation script referenced in
// SCENARIO-0114's evidence notes.
type vector struct {
	Name          string `json:"name"`
	Username      string `json:"username"`
	Password      string `json:"password"`
	Protocol      string `json:"protocol"`
	Iterations    int    `json:"iterations"`
	SaltHex       string `json:"salt_hex"`
	AHexSecret    string `json:"a_hex"`
	BHex          string `json:"b_hex"`
	DerivedKeyHex string `json:"derived_key_hex"`
	AHex          string `json:"A_hex"`
	M1Hex         string `json:"M1_hex"`
	HAMKHex       string `json:"H_AMK_hex"`
	KHex          string `json:"K_hex"`
}

func loadVectors(t *testing.T) []vector {
	t.Helper()
	data, err := os.ReadFile("testdata/vectors.json")
	if err != nil {
		t.Fatalf("reading testdata/vectors.json: %v", err)
	}
	var vecs []vector
	if err := json.Unmarshal(data, &vecs); err != nil {
		t.Fatalf("parsing testdata/vectors.json: %v", err)
	}
	if len(vecs) == 0 {
		t.Fatal("no vectors loaded")
	}
	return vecs
}

func mustHex(t *testing.T, s string) []byte {
	t.Helper()
	b, err := hex.DecodeString(s)
	if err != nil {
		t.Fatalf("bad hex %q: %v", s, err)
	}
	return b
}

// TestSRPHandshakeAgainstKnownVectors is SCENARIO-0114's automation: the SRP
// handshake implementation runs against known SRP-6a + PBKDF2 s2k test
// vectors matching Apple's variant, entirely offline.
func TestSRPHandshakeAgainstKnownVectors(t *testing.T) {
	for _, v := range loadVectors(t) {
		v := v
		t.Run(v.Name, func(t *testing.T) {
			salt := mustHex(t, v.SaltHex)
			ephemeralSecret := mustHex(t, v.AHexSecret)
			B := mustHex(t, v.BHex)
			wantA := mustHex(t, v.AHex)
			wantDerived := mustHex(t, v.DerivedKeyHex)
			wantM1 := mustHex(t, v.M1Hex)
			wantHAMK := mustHex(t, v.HAMKHex)
			wantK := mustHex(t, v.KHex)

			derived, err := DerivePassword(v.Password, Protocol(v.Protocol), salt, v.Iterations)
			if err != nil {
				t.Fatalf("DerivePassword: %v", err)
			}
			if hex.EncodeToString(derived) != hex.EncodeToString(wantDerived) {
				t.Fatalf("derived password key mismatch:\n got %x\nwant %x", derived, wantDerived)
			}

			client, err := NewClient(v.Username, ephemeralSecret)
			if err != nil {
				t.Fatalf("NewClient: %v", err)
			}
			gotA := client.PublicKey()
			if hex.EncodeToString(gotA) != hex.EncodeToString(wantA) {
				t.Fatalf("public key A mismatch:\n got %x\nwant %x", gotA, wantA)
			}

			result, err := client.ProcessChallenge(salt, B, derived)
			if err != nil {
				t.Fatalf("ProcessChallenge: %v", err)
			}

			if hex.EncodeToString(result.M1) != hex.EncodeToString(wantM1) {
				t.Fatalf("M1 mismatch:\n got %x\nwant %x", result.M1, wantM1)
			}
			if hex.EncodeToString(result.ClientHAMK) != hex.EncodeToString(wantHAMK) {
				t.Fatalf("HAMK mismatch:\n got %x\nwant %x", result.ClientHAMK, wantHAMK)
			}
			if hex.EncodeToString(result.SessionKey) != hex.EncodeToString(wantK) {
				t.Fatalf("session key K mismatch:\n got %x\nwant %x", result.SessionKey, wantK)
			}

			if !VerifyServerProof(result, wantHAMK) {
				t.Fatal("VerifyServerProof rejected the vector's own expected HAMK")
			}
			forged := append([]byte(nil), wantHAMK...)
			forged[0] ^= 0xFF
			if VerifyServerProof(result, forged) {
				t.Fatal("VerifyServerProof accepted a forged server proof")
			}
		})
	}
}

func TestProcessChallenge_RejectsZeroB(t *testing.T) {
	client, err := NewClient("user@example.com", nil)
	if err != nil {
		t.Fatalf("NewClient: %v", err)
	}
	zeroB := make([]byte, 32) // B == 0 mod N regardless of N's size
	_, err = client.ProcessChallenge([]byte("salt"), zeroB, []byte("derivedkey"))
	if err != ErrSafetyCheckFailed {
		t.Fatalf("expected ErrSafetyCheckFailed, got %v", err)
	}
}

func TestDerivePassword_RejectsUnknownProtocol(t *testing.T) {
	_, err := DerivePassword("pw", "bogus", []byte("salt"), 1000)
	if err == nil {
		t.Fatal("expected error for unknown protocol")
	}
}

func TestDerivePassword_RejectsNonPositiveIterations(t *testing.T) {
	_, err := DerivePassword("pw", ProtocolS2K, []byte("salt"), 0)
	if err == nil {
		t.Fatal("expected error for zero iterations")
	}
}

func TestNewClient_RejectsWrongEphemeralSecretLength(t *testing.T) {
	_, err := NewClient("user@example.com", []byte{1, 2, 3})
	if err == nil {
		t.Fatal("expected error for short ephemeral secret")
	}
}
