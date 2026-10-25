-- Identity fog: optional authored descriptor carried on the manifest row.
-- True names stay in the log/projection; KnownState gates the display label.

ALTER TABLE scene_manifest
    ADD COLUMN descriptor text;

-- HIGH-3 checkpoint bump, lockstep with folds.PROJECTOR_VERSIONS['scene_manifest']=2.
UPDATE projection_checkpoint
    SET projector_version = 2, updated_at = now()
    WHERE projection_name = 'scene_manifest';
