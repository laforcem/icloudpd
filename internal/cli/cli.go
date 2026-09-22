// Package cli implements the walking skeleton's subcommands: serve
// (container default), run-once, and check-protocol. There is deliberately
// no migrate subcommand (STORY-0030 AC-2) — everything else in the rewrite
// is already a clean break (fresh auth, fresh manifest), so there is no
// built-in path to convert the old Python YAML config.
package cli

import (
	"context"
	"fmt"
	"log/slog"
	"os"
	"os/signal"
	"syscall"

	"github.com/laforcem/icloudpd/internal/app"
	"github.com/laforcem/icloudpd/internal/config"
)

// DefaultCommand is what runs when the binary is invoked with no explicit
// subcommand — the container image's default (STORY-0030 AC-1).
const DefaultCommand = "serve"

// Run dispatches args[0] (if present) to the matching subcommand, or
// DefaultCommand if args is empty. configPath names the YAML config file
// every subcommand loads.
func Run(ctx context.Context, args []string, configPath string) error {
	cmd := DefaultCommand
	if len(args) > 0 {
		cmd = args[0]
	}

	logger := slog.Default()

	switch cmd {
	case "serve":
		return Serve(ctx, configPath, logger)
	case "run-once":
		return RunOnce(ctx, configPath, logger)
	case "check-protocol":
		return CheckProtocol(ctx, configPath, logger)
	default:
		return fmt.Errorf("cli: unknown subcommand %q", cmd)
	}
}

// RunOnce loads config, runs a single synchronous pass over every
// configured account, and returns. The process exits after this call
// returns rather than staying resident — independent of serve's lifecycle
// (SCENARIO-0021).
func RunOnce(ctx context.Context, configPath string, logger *slog.Logger) error {
	cfg, err := config.Load(configPath)
	if err != nil {
		return err
	}
	results, err := app.RunOnce(ctx, cfg, logger)
	for account, result := range results {
		logger.Info("account run complete", "account", account, "assets_downloaded", result.AssetsDownloaded)
	}
	return err
}

// Serve starts the always-on process. Scheduling (cron-driven repeated
// sync) and the health/metrics listener are TODO(ITER-0003)/TODO(ITER-0004)
// — not part of the walking skeleton's committed scope. Serve still
// performs one initial sync pass so the container is doing useful work
// immediately, then blocks until a termination signal, matching the
// "long-running, not one-shot" lifecycle SCENARIO-0021 checks for.
func Serve(ctx context.Context, configPath string, logger *slog.Logger) error {
	logger.Info("serve starting (scheduler and health listener land in ITER-0003/ITER-0004; this iteration performs one initial sync then stays resident)")

	cfg, err := config.Load(configPath)
	if err != nil {
		return err
	}
	if _, err := app.RunOnce(ctx, cfg, logger); err != nil {
		logger.Error("initial sync failed", "error", err)
	}

	sigCh := make(chan os.Signal, 1)
	signal.Notify(sigCh, syscall.SIGINT, syscall.SIGTERM)
	select {
	case <-ctx.Done():
		return ctx.Err()
	case sig := <-sigCh:
		logger.Info("received signal, exiting", "signal", sig.String())
		return nil
	}
}

// CheckProtocol runs the SRP handshake against a live account and prints a
// pass/fail result — a manual verification command with no CI involvement
// (STORY-0001 AC-3 / SCENARIO-0121).
func CheckProtocol(ctx context.Context, configPath string, logger *slog.Logger) error {
	cfg, err := config.Load(configPath)
	if err != nil {
		return err
	}
	if len(cfg.Accounts) == 0 {
		return fmt.Errorf("cli: check-protocol needs at least one configured account")
	}

	acct := cfg.Accounts[0]
	_, err = app.SignIn(ctx, cfg, acct, logger)
	if err != nil {
		fmt.Printf("check-protocol: FAIL (%s): %v\n", acct.Name, err)
		return err
	}
	fmt.Printf("check-protocol: PASS (%s): SRP auth + accountLogin succeeded\n", acct.Name)
	return nil
}
