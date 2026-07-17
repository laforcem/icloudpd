# icloudpd

A command-line tool to download media from iCloud Photos. This is a Docker-first fork of [icloud_photos_downloader](https://github.com/icloud-photos-downloader/icloud_photos_downloader).

> [!NOTE]
> Full docs are being rewritten from scratch, which effort is being tracked in #22. This README is a placeholder for the interim.

## Run it

For the full list of config options:

```sh
docker run -it --rm ghcr.io/laforcem/icloudpd:latest --help
```

### Normal Docker run

```sh
docker run -it --rm --name icloudpd -v $(pwd)/Photos:/data -e TZ=America/Los_Angeles ghcr.io/laforcem/icloudpd:latest --directory /data --username my@email.address --watch-with-interval 3600
```

### Docker Compose

It's recommended that you use a config file instead of passing CLI arguments into Compose. See [compose.example.yml](./compose.example.yaml) and [config.example.yaml](./config.example.yaml).
