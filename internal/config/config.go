// Package config is a minimal YAML loader for the walking skeleton. Full
// schema validation, provenance tracking, and print-config redaction are
// STORY-0138/EPIC-022, deferred to ITER-0002 — this package only reads
// enough to wire syncengine.Options.
package config

import (
	"fmt"
	"os"
	"strings"

	"gopkg.in/yaml.v3"
)

// Account is one configured iCloud account. Credential resolution here is a
// deliberately thin approximation of the design's eventual watched-file
// source chain (EPIC-013/014, not committed to this iteration): a plain
// file path read once at startup, not watched, no env/cache fallback.
type Account struct {
	Name         string `yaml:"name"`
	AppleID      string `yaml:"apple_id,omitempty"`      // inline value, if not read from a file
	AppleIDFile  string `yaml:"apple_id_file,omitempty"` // preferred: keeps the account identity out of config.yaml itself
	PasswordFile string `yaml:"password_file"`
	DownloadDir  string `yaml:"download_dir"`
	Domain       string `yaml:"domain"` // "com" or "cn"; defaults to "com"
}

// Config is the walking skeleton's whole configuration surface.
type Config struct {
	StateDir string    `yaml:"state_dir"`
	Accounts []Account `yaml:"accounts"`
}

// Load reads and parses a config file at path. It does not validate beyond
// what's needed to avoid a nil-pointer at call sites — real validation
// (`validate` subcommand, required-field checks) is STORY-0138.
func Load(path string) (*Config, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return nil, fmt.Errorf("config: reading %s: %w", path, err)
	}
	var cfg Config
	if err := yaml.Unmarshal(data, &cfg); err != nil {
		return nil, fmt.Errorf("config: parsing %s: %w", path, err)
	}
	for i := range cfg.Accounts {
		if cfg.Accounts[i].Domain == "" {
			cfg.Accounts[i].Domain = "com"
		}
		if cfg.Accounts[i].AppleIDFile != "" {
			data, err := os.ReadFile(cfg.Accounts[i].AppleIDFile)
			if err != nil {
				return nil, fmt.Errorf("config: reading apple_id_file %s for account %s: %w", cfg.Accounts[i].AppleIDFile, cfg.Accounts[i].Name, err)
			}
			cfg.Accounts[i].AppleID = strings.TrimRight(string(data), "\n")
		}
	}
	return &cfg, nil
}

// ReadPassword reads an account's password from its configured file,
// trimming a single trailing newline if present (matching how a secret file
// is typically written by `echo` or an editor).
func ReadPassword(account Account) (string, error) {
	data, err := os.ReadFile(account.PasswordFile)
	if err != nil {
		return "", fmt.Errorf("config: reading password file %s for account %s: %w", account.PasswordFile, account.Name, err)
	}
	return strings.TrimRight(string(data), "\n"), nil
}
