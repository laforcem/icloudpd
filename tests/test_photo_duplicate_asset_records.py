from unittest import TestCase, mock

from pyicloud_ipd.services.photos import PhotoAlbum


def make_response(records):
    resp = mock.Mock()
    resp.json.return_value = {"records": records}
    return resp


def master_record(record_name):
    return {
        "recordType": "CPLMaster",
        "recordName": record_name,
        "recordChangeTag": "m",
        "fields": {},
    }


def asset_record(record_name, master_id, added_date, asset_date=1000, extra_fields=None):
    fields = {
        "masterRef": {"value": {"recordName": master_id}, "type": "REFERENCE"},
        "assetDate": {"value": asset_date, "type": "INT64"},
    }
    if added_date is not None:
        fields["addedDate"] = {"value": added_date, "type": "INT64"}
    if extra_fields:
        fields.update(extra_fields)
    return {
        "recordType": "CPLAsset",
        "recordName": record_name,
        "recordChangeTag": "a",
        "fields": fields,
    }


def make_album(page_response):
    album = PhotoAlbum(
        params={},
        session=mock.Mock(),
        service_endpoint="https://example.com",
        name="",
        list_type="CPLAssetAndMasterByAssetDateWithoutHiddenOrDeleted",
        obj_type="CPLAssetByAssetDateWithoutHiddenOrDeleted",
    )
    empty_response = make_response([])
    with mock.patch.object(
        PhotoAlbum, "photos_request", side_effect=[page_response, empty_response]
    ):
        return list(album.photos)


class DuplicateAssetRecordTestCase(TestCase):
    def test_keeps_asset_record_with_later_added_date(self) -> None:
        # The newer record (ASSET_NEW) appears FIRST in the raw response,
        # and the older one (ASSET_OLD) appears LAST. A naive "last one
        # wins" dict assignment would incorrectly keep ASSET_OLD.
        records = [
            master_record("MASTER1"),
            asset_record("ASSET_NEW", "MASTER1", added_date=2000),
            asset_record("ASSET_OLD", "MASTER1", added_date=1000),
        ]

        photos = make_album(make_response(records))

        self.assertEqual(len(photos), 1)
        self.assertEqual(photos[0]._asset_record["recordName"], "ASSET_NEW")

    def test_logs_warning_when_duplicate_asset_records_found(self) -> None:
        records = [
            master_record("MASTER1"),
            asset_record("ASSET_NEW", "MASTER1", added_date=2000),
            asset_record("ASSET_OLD", "MASTER1", added_date=1000),
        ]

        with self.assertLogs("pyicloud_ipd.services.photos", level="WARNING") as cm:
            make_album(make_response(records))

        self.assertTrue(
            any("Keeping newest of duplicate metadata for asset MASTER1" in m for m in cm.output)
        )

    def test_keeps_newest_of_three_duplicate_asset_records(self) -> None:
        # NEWEST arrives first, MID arrives last, so a naive "last one
        # wins" dict assignment would incorrectly keep MID.
        records = [
            master_record("MASTER1"),
            asset_record("ASSET_NEWEST", "MASTER1", added_date=2000),
            asset_record("ASSET_OLDEST", "MASTER1", added_date=1000),
            asset_record("ASSET_MID", "MASTER1", added_date=1500),
        ]

        photos = make_album(make_response(records))

        self.assertEqual(len(photos), 1)
        self.assertEqual(photos[0]._asset_record["recordName"], "ASSET_NEWEST")

    def test_keeps_record_with_added_date_over_one_missing_it(self) -> None:
        # ASSET_HAS_DATE arrives first, ASSET_NO_DATE arrives last, so a
        # naive "last one wins" dict assignment would incorrectly keep
        # the one missing addedDate.
        records = [
            master_record("MASTER1"),
            asset_record("ASSET_HAS_DATE", "MASTER1", added_date=1000),
            asset_record("ASSET_NO_DATE", "MASTER1", added_date=None),
        ]

        photos = make_album(make_response(records))

        self.assertEqual(len(photos), 1)
        self.assertEqual(photos[0]._asset_record["recordName"], "ASSET_HAS_DATE")
