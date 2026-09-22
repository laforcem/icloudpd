// Command icloudpd is the Go rewrite's single binary: subcommand dispatch
// only (STORY-0030). All real work lives in internal/cli and internal/app.
package main

import (
	"context"
	"flag"
	"fmt"
	"os"
	"os/signal"
	"syscall"

	"github.com/laforcem/icloudpd/internal/cli"
)

func main() {
	configPath := flag.String("config", "config.yaml", "path to the YAML config file")
	flag.Parse()

	ctx, stop := signal.NotifyContext(context.Background(), syscall.SIGINT, syscall.SIGTERM)
	defer stop()

	if err := cli.Run(ctx, flag.Args(), *configPath); err != nil {
		fmt.Fprintln(os.Stderr, "icloudpd:", err)
		os.Exit(1)
	}
}
