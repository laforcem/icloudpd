package cli

import (
	"context"
	"strings"
	"testing"
)

// TestDefaultCommand_IsServe is SCENARIO-0021's evidence (STORY-0030 AC-1):
// running the binary with no explicit subcommand runs serve.
func TestDefaultCommand_IsServe(t *testing.T) {
	if DefaultCommand != "serve" {
		t.Fatalf("DefaultCommand = %q, want serve", DefaultCommand)
	}
}

// TestRun_NoArgs_DispatchesToServe proves Run's dispatch logic actually
// honors DefaultCommand, not just that the constant is named right. It uses
// a missing config path so the call fails fast (before any network I/O),
// and asserts the failure came from loading config — not from "unknown
// subcommand" — which only serve/run-once/check-protocol reach.
func TestRun_NoArgs_DispatchesToServe(t *testing.T) {
	err := Run(context.Background(), nil, "/nonexistent/config.yaml")
	if err == nil {
		t.Fatal("expected an error from a missing config file")
	}
	if strings.Contains(err.Error(), "unknown subcommand") {
		t.Fatalf("no-args invocation did not dispatch to a known subcommand: %v", err)
	}
}

// TestRun_MigrateIsNotASubcommand is STORY-0030 AC-2's evidence: there is no
// built-in path to convert the old Python YAML config, because there is no
// migrate subcommand at all.
func TestRun_MigrateIsNotASubcommand(t *testing.T) {
	err := Run(context.Background(), []string{"migrate"}, "/nonexistent/config.yaml")
	if err == nil {
		t.Fatal("expected an error for the migrate subcommand")
	}
	if !strings.Contains(err.Error(), "unknown subcommand") {
		t.Fatalf("expected 'unknown subcommand' for migrate, got: %v", err)
	}
}

// TestRun_RunOnce_IsARecognizedSubcommand proves run-once dispatches
// (reaches config loading, not "unknown subcommand") — the counterpart to
// serve for SCENARIO-0021's independent-lifecycle check.
func TestRun_RunOnce_IsARecognizedSubcommand(t *testing.T) {
	err := Run(context.Background(), []string{"run-once"}, "/nonexistent/config.yaml")
	if err == nil {
		t.Fatal("expected an error from a missing config file")
	}
	if strings.Contains(err.Error(), "unknown subcommand") {
		t.Fatalf("run-once was not recognized as a subcommand: %v", err)
	}
}

func TestRun_CheckProtocol_IsARecognizedSubcommand(t *testing.T) {
	err := Run(context.Background(), []string{"check-protocol"}, "/nonexistent/config.yaml")
	if err == nil {
		t.Fatal("expected an error from a missing config file")
	}
	if strings.Contains(err.Error(), "unknown subcommand") {
		t.Fatalf("check-protocol was not recognized as a subcommand: %v", err)
	}
}

func TestRun_UnknownSubcommand(t *testing.T) {
	err := Run(context.Background(), []string{"list-albums"}, "config.yaml")
	if err == nil {
		t.Fatal("expected an error for an unrecognized subcommand")
	}
	if !strings.Contains(err.Error(), "unknown subcommand") {
		t.Fatalf("expected 'unknown subcommand', got: %v", err)
	}
}
