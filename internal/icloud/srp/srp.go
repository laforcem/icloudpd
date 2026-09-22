// Package srp implements the SRP-6a client handshake and Apple's PBKDF2-based
// "s2k"/"s2k_fo" password key derivation, matching the variant used by
// idmsa.apple.com: RFC 5054's 2048-bit N/g group and zero-padding rules,
// SHA-256 throughout, and no username folded into x (Apple's server-side
// verifier is keyed on the account alone, not username+password).
//
// This package is pure computation: no network I/O. See srp_test.go for
// correctness against fixed vectors generated from the reference Python
// `srp` library (the same one pyicloud_ipd uses against live Apple servers).
package srp

import (
	"crypto/hmac"
	"crypto/rand"
	"crypto/sha256"
	"crypto/subtle"
	"errors"
	"fmt"
	"hash"
	"math/big"
)

// Protocol identifies which password-key-derivation variant Apple's server
// requested during signin/init.
type Protocol string

const (
	ProtocolS2K   Protocol = "s2k"
	ProtocolS2KFO Protocol = "s2k_fo"
)

// group2048Hex is RFC 5054's 2048-bit safe prime, generator g=2.
const group2048Hex = "AC6BDB41324A9A9BF166DE5E1389582FAF72B6651987EE07FC3192943DB56050A37329CBB4" +
	"A099ED8193E0757767A13DD52312AB4B03310DCD7F48A9DA04FD50E8083969EDB767B0CF60" +
	"95179A163AB3661A05FBD5FAAAE82918A9962F0B93B855F97993EC975EEAA80D740ADBF4FF" +
	"747359D041D5C33EA71D281E446B14773BCA97B43A23FB801676BD207A436C6481F1D2B907" +
	"8717461A5B9D32E688F87748544523B524B0D57D5EA77A2775D2ECFA032CFBDBF52FB37861" +
	"60279004E57AE6AF874E7303CE53299CCC041C7BC308D82A5698F3A8D0C38271AE35F8E9DB" +
	"FBB694B5C803D89F7AE435DE236D525F54759B65E372FCD68EF20FA7111F9E4AFF73"

var (
	groupN = mustHexInt(group2048Hex)
	groupG = big.NewInt(2)
	nLen   = (groupN.BitLen() + 7) / 8 // 256 bytes for the 2048-bit group
)

func mustHexInt(s string) *big.Int {
	n, ok := new(big.Int).SetString(s, 16)
	if !ok {
		panic("srp: invalid group prime literal")
	}
	return n
}

func newHash() hash.Hash { return sha256.New() }

// padLeft left-pads b with zero bytes to width, matching RFC 5054's PAD().
// It never truncates: b must already fit within width.
func padLeft(b []byte, width int) []byte {
	if len(b) >= width {
		return b
	}
	out := make([]byte, width)
	copy(out[width-len(b):], b)
	return out
}

// DerivePassword applies Apple's PBKDF2 s2k/s2k_fo password key derivation.
// s2k hashes the SHA-256 digest bytes as the PBKDF2 password; s2k_fo hashes
// the hex-encoded digest string instead (an Apple quirk, "fo" = "fix old").
func DerivePassword(password string, protocol Protocol, salt []byte, iterations int) ([]byte, error) {
	if iterations <= 0 {
		return nil, fmt.Errorf("srp: iterations must be positive, got %d", iterations)
	}
	digest := sha256.Sum256([]byte(password))
	var pbkdf2Password []byte
	switch protocol {
	case ProtocolS2K:
		pbkdf2Password = digest[:]
	case ProtocolS2KFO:
		pbkdf2Password = []byte(fmt.Sprintf("%x", digest))
	default:
		return nil, fmt.Errorf("srp: unknown protocol %q", protocol)
	}
	return pbkdf2HMACSHA256(pbkdf2Password, salt, iterations, 32), nil
}

// pbkdf2HMACSHA256 implements PBKDF2 (RFC 8018) with HMAC-SHA256, avoiding a
// dependency on golang.org/x/crypto for one small primitive.
func pbkdf2HMACSHA256(password, salt []byte, iterations, keyLen int) []byte {
	prf := hmac.New(sha256.New, password)
	hLen := prf.Size()
	numBlocks := (keyLen + hLen - 1) / hLen

	dk := make([]byte, 0, numBlocks*hLen)
	buf := make([]byte, len(salt)+4)
	copy(buf, salt)

	for block := 1; block <= numBlocks; block++ {
		buf[len(salt)] = byte(block >> 24)
		buf[len(salt)+1] = byte(block >> 16)
		buf[len(salt)+2] = byte(block >> 8)
		buf[len(salt)+3] = byte(block)

		prf.Reset()
		prf.Write(buf)
		u := prf.Sum(nil)
		t := make([]byte, hLen)
		copy(t, u)

		for i := 1; i < iterations; i++ {
			prf.Reset()
			prf.Write(u)
			u = prf.Sum(nil)
			for j := range t {
				t[j] ^= u[j]
			}
		}
		dk = append(dk, t...)
	}
	return dk[:keyLen]
}

// multiplierK computes SRP-6a's k = H(PAD(N) || PAD(g)).
func multiplierK() *big.Int {
	h := newHash()
	h.Write(padLeft(groupN.Bytes(), nLen))
	h.Write(padLeft(groupG.Bytes(), nLen))
	return new(big.Int).SetBytes(h.Sum(nil))
}

// Client holds one client-side SRP-6a handshake in progress.
type Client struct {
	username string
	a        *big.Int
	A        *big.Int
	k        *big.Int
}

// NewClient starts a handshake for username, generating a fresh 256-bit
// ephemeral private key a (or using ephemeralSecret if non-nil, for
// deterministic tests — 32 bytes exactly, matching what real Apple traffic
// uses in practice). It returns the client alongside the public A to send to
// the server as signin/init's "a" parameter.
func NewClient(username string, ephemeralSecret []byte) (*Client, error) {
	var aBytes []byte
	if ephemeralSecret != nil {
		if len(ephemeralSecret) != 32 {
			return nil, fmt.Errorf("srp: ephemeral secret must be 32 bytes, got %d", len(ephemeralSecret))
		}
		aBytes = ephemeralSecret
	} else {
		aBytes = make([]byte, 32)
		if _, err := rand.Read(aBytes); err != nil {
			return nil, fmt.Errorf("srp: generating ephemeral secret: %w", err)
		}
	}

	a := new(big.Int).SetBytes(aBytes)
	A := new(big.Int).Exp(groupG, a, groupN)

	return &Client{
		username: username,
		a:        a,
		A:        A,
		k:        multiplierK(),
	}, nil
}

// PublicKey returns A's big-endian bytes, to send as the "a" field of
// signin/init (Apple's field name for the client's public ephemeral key).
func (c *Client) PublicKey() []byte {
	return c.A.Bytes()
}

// ErrSafetyCheckFailed indicates the server's B (or the derived u) violates
// SRP-6a's safety checks — B mod N == 0, or u == 0. A conforming server
// should never produce this; treat it as a protocol-level failure, not a
// wrong-password signal.
var ErrSafetyCheckFailed = errors.New("srp: SRP-6a safety check failed")

// ChallengeResult carries the values the client sends onward to
// signin/complete (M1, HAMK) plus the derived session key K, in case a
// caller needs it for a later step.
type ChallengeResult struct {
	M1         []byte // client proof, sent as "m1"
	ClientHAMK []byte // client's expected server proof, sent as "m2"
	SessionKey []byte // K, rarely needed beyond this handshake
}

// ProcessChallenge consumes the server's signin/init response (salt, B) plus
// the already-PBKDF2-derived password key (see DerivePassword), and computes
// the client's proof M1 and expected server proof HAMK per SRP-6a with
// Apple's no-username-in-x variant: x = H(salt || H(derivedKey)).
func (c *Client) ProcessChallenge(salt, B, derivedKey []byte) (*ChallengeResult, error) {
	Bn := new(big.Int).SetBytes(B)
	if new(big.Int).Mod(Bn, groupN).Sign() == 0 {
		return nil, ErrSafetyCheckFailed
	}

	u := c.scramblingU(Bn)
	if u.Sign() == 0 {
		return nil, ErrSafetyCheckFailed
	}

	x := c.privateKeyX(salt, derivedKey)
	v := new(big.Int).Exp(groupG, x, groupN)

	// S = (B - k*v) ^ (a + u*x) mod N
	kv := new(big.Int).Mul(c.k, v)
	base := new(big.Int).Sub(Bn, kv)
	base.Mod(base, groupN)
	exp := new(big.Int).Mul(u, x)
	exp.Add(exp, c.a)
	S := new(big.Int).Exp(base, exp, groupN)

	h := newHash()
	h.Write(S.Bytes())
	K := h.Sum(nil)

	M1 := calculateM(groupN, groupG, c.username, salt, c.A, Bn, K)
	hamk := calculateHAMK(c.A, M1, K)

	return &ChallengeResult{M1: M1, ClientHAMK: hamk, SessionKey: K}, nil
}

// scramblingU computes u = H(PAD(A) || PAD(B)).
func (c *Client) scramblingU(B *big.Int) *big.Int {
	h := newHash()
	h.Write(padLeft(c.A.Bytes(), nLen))
	h.Write(padLeft(B.Bytes(), nLen))
	return new(big.Int).SetBytes(h.Sum(nil))
}

// privateKeyX computes x = H(salt || H("" + ":" + derivedKey)) — the empty
// string in place of username is Apple's no-username-in-x variant.
func (c *Client) privateKeyX(salt, derivedKey []byte) *big.Int {
	inner := newHash()
	inner.Write([]byte(":"))
	inner.Write(derivedKey)
	innerDigest := inner.Sum(nil)

	outer := newHash()
	outer.Write(salt)
	outer.Write(innerDigest)
	return new(big.Int).SetBytes(outer.Sum(nil))
}

// hNxorG computes H(N) XOR H(PAD(g)), the first component of calculateM.
func hNxorG(N, g *big.Int) []byte {
	hn := newHash()
	hn.Write(N.Bytes())
	hnSum := hn.Sum(nil)

	hg := newHash()
	hg.Write(padLeft(g.Bytes(), len(N.Bytes())))
	hgSum := hg.Sum(nil)

	out := make([]byte, len(hnSum))
	for i := range out {
		out[i] = hnSum[i] ^ hgSum[i]
	}
	return out
}

func calculateM(N, g *big.Int, username string, salt []byte, A, B *big.Int, K []byte) []byte {
	h := newHash()
	h.Write(hNxorG(N, g))
	idHash := sha256.Sum256([]byte(username))
	h.Write(idHash[:])
	h.Write(salt)
	h.Write(A.Bytes())
	h.Write(B.Bytes())
	h.Write(K)
	return h.Sum(nil)
}

func calculateHAMK(A *big.Int, M, K []byte) []byte {
	h := newHash()
	h.Write(A.Bytes())
	h.Write(M)
	h.Write(K)
	return h.Sum(nil)
}

// VerifyServerProof checks Apple's returned server proof against the
// client's own expected value in constant time.
func VerifyServerProof(result *ChallengeResult, serverHAMK []byte) bool {
	return subtle.ConstantTimeCompare(result.ClientHAMK, serverHAMK) == 1
}
