# RAW Image Storage Options

## Current State

Currently, GhostRoll:
- ✅ **Detects** RAW files (`.arw`, `.cr2`, `.cr3`, `.nef`, `.dng`, `.raf`, `.rw2`)
- ✅ **Copies** RAW files to local `originals/DCIM/` directory (preserving structure)
- ✅ **Tracks** RAW files in database for deduplication
- ❌ **Does NOT upload** RAW files to S3 (only JPEG derivatives are uploaded)

**What gets uploaded to S3:**
- `sessions/<SESSION_ID>/share/` - Share-friendly JPEGs (max ~2048px)
- `sessions/<SESSION_ID>/thumbs/` - Thumbnails (max ~512px)
- `sessions/<SESSION_ID>/enhanced/` - Auto-enhanced versions (via Lambda)
- `sessions/<SESSION_ID>/share.zip` - Downloadable zip
- `sessions/<SESSION_ID>/index.html` - Gallery HTML

**What stays local only:**
- `originals/DCIM/` - All original files (JPEG + RAW)

## Options for Keeping RAW Images

### Option 1: Upload RAW Files to S3 (Simple)

**Approach:** Upload RAW files to S3 in a separate prefix, mirroring the local structure.

**S3 Structure:**
```
sessions/<SESSION_ID>/
  ├── share/          (existing - JPEG derivatives)
  ├── thumbs/         (existing - thumbnails)
  ├── enhanced/       (existing - enhanced images)
  ├── originals/      (NEW - RAW files + original JPEGs)
  │   └── DCIM/
  │       └── [preserved structure]
  ├── index.html
  └── share.zip
```

**Pros:**
- Simple implementation
- Complete backup of originals in cloud
- Preserves directory structure
- Can access RAW files via presigned URLs if needed
- No additional configuration needed

**Cons:**
- Increases S3 storage costs (RAW files are large, typically 20-50MB each)
- Longer upload times (especially on slower connections)
- Uses standard S3 storage class (more expensive than archival)

**Implementation:**
- Add RAW files to upload queue after copying to originals
- Upload to `{prefix}/originals/DCIM/{relative_path}`
- Use same upload deduplication logic (skip if already uploaded)

**Estimated Cost Impact:**
- Example: 100 RAW files × 30MB = 3GB per session
- S3 Standard: ~$0.023/GB/month = ~$0.07/month per session
- For 10 sessions/month: ~$0.70/month

---

### Option 2: Upload RAW Files with Configurable Toggle

**Approach:** Same as Option 1, but add a configuration option to enable/disable RAW uploads.

**Configuration:**
```python
# In config.py
upload_raw_files: bool = False  # Default: don't upload (backward compatible)
```

**Pros:**
- User controls whether to upload RAW files
- Backward compatible (default: off)
- Can enable/disable per session or globally
- Good for users who want local-only RAW storage initially

**Cons:**
- Adds configuration complexity
- Users need to decide upfront

**Implementation:**
- Add `upload_raw_files` config option
- Conditionally add RAW files to upload queue
- Document in README/config examples

---

### Option 3: Upload RAW Files to S3 Glacier/Deep Archive

**Approach:** Upload RAW files to S3 with lifecycle policy to transition to cheaper storage classes.

**S3 Structure:**
```
sessions/<SESSION_ID>/
  ├── share/          (Standard storage)
  ├── thumbs/         (Standard storage)
  ├── enhanced/       (Standard storage)
  ├── originals/      (Glacier/Deep Archive after 30 days)
  └── ...
```

**Pros:**
- Much lower storage costs for long-term archival
- Glacier Instant Retrieval: ~$0.004/GB/month (vs $0.023 for Standard)
- Deep Archive: ~$0.00099/GB/month (cheapest, but 12-hour retrieval)
- Good for "set it and forget it" archival

**Cons:**
- More complex implementation (lifecycle policies, storage class management)
- Retrieval costs if you need to download (Glacier: $0.03/GB, Deep Archive: $0.02/GB)
- Retrieval time delays (Instant: immediate, Deep Archive: 12 hours)
- Not suitable for frequent access

**Implementation:**
- Upload to S3 Standard initially
- Configure bucket lifecycle policy to transition `originals/` prefix to Glacier after 30 days
- Or use S3 Intelligent-Tiering for automatic optimization

**Estimated Cost Impact:**
- Same 3GB per session example
- Glacier Instant Retrieval: ~$0.012/month per session (vs $0.07 Standard)
- Deep Archive: ~$0.003/month per session (cheapest, but slow retrieval)

---

### Option 4: Separate Archive Bucket/Prefix

**Approach:** Upload RAW files to a completely separate S3 location (different bucket or root prefix).

**S3 Structure:**
```
# Shareable gallery (existing)
sessions/<SESSION_ID>/
  ├── share/
  ├── thumbs/
  └── index.html

# Archive (new)
archive/<SESSION_ID>/
  └── originals/
      └── DCIM/
```

**Pros:**
- Complete separation of concerns
- Can apply different lifecycle policies
- Can use different bucket permissions
- Gallery links don't expose RAW file structure
- Can archive to different region for disaster recovery

**Cons:**
- More complex configuration (two buckets/prefixes)
- More complex code (tracking two upload locations)
- Harder to correlate sessions with archives

**Implementation:**
- Add `archive_bucket` or `archive_prefix` config option
- Upload RAW files to archive location
- Keep gallery uploads in existing location

---

### Option 5: Hybrid - Upload JPEG Originals, Archive RAW Separately

**Approach:** Upload original JPEGs to S3 (for gallery backup), but handle RAW files separately (local-only or separate archive).

**S3 Structure:**
```
sessions/<SESSION_ID>/
  ├── share/          (derived JPEGs)
  ├── thumbs/         (thumbnails)
  ├── originals/      (original JPEGs only, not RAW)
  │   └── DCIM/
  └── ...
```

**Pros:**
- Smaller uploads (JPEG originals are smaller than RAW)
- Still have backup of original JPEGs
- RAW files can be handled separately (manual backup, external drive, etc.)
- Lower S3 costs than uploading RAW

**Cons:**
- RAW files not in cloud backup
- Incomplete backup if you care about RAW files
- More complex logic (filter RAW vs JPEG)

**Implementation:**
- Upload original JPEGs to `originals/` prefix
- Skip RAW files (or handle separately)
- Could add separate config for RAW handling

---

### Option 6: Compress RAW Files Before Upload

**Approach:** Compress RAW files (e.g., using lossless compression like ZIP or 7z) before uploading.

**S3 Structure:**
```
sessions/<SESSION_ID>/
  ├── share/
  ├── thumbs/
  ├── originals/      (compressed RAW files)
  │   └── DCIM/
  │       └── [RAW files as .zip or .7z]
  └── ...
```

**Pros:**
- Reduces upload size and storage costs
- Faster uploads
- Still preserves RAW files

**Cons:**
- Requires decompression to use RAW files
- Adds processing time (compression step)
- More complex implementation
- RAW files not immediately usable

**Implementation:**
- Compress RAW files after copying to originals
- Upload compressed files
- Document compression format in metadata

**Estimated Savings:**
- RAW files typically compress 10-30% (depends on format)
- Example: 3GB → 2.4GB (20% reduction)
- Saves ~$0.014/month per session

---

## Recommendation

**For most users: Option 2 (Configurable Toggle) + Option 3 (Lifecycle to Glacier)**

This gives you:
1. **Flexibility** - Enable/disable RAW uploads via config
2. **Cost efficiency** - Use lifecycle policies to move to cheaper storage after 30 days
3. **Backward compatibility** - Default off, so existing users aren't affected
4. **Future-proof** - Can adjust storage class or policies later

**Implementation Priority:**
1. **Phase 1:** Add config option + basic RAW upload (Option 2)
2. **Phase 2:** Add lifecycle policy support for Glacier transition (Option 3)

## Implementation Considerations

### Upload Strategy
- **Parallel uploads** - RAW files are large, benefit from parallel upload workers
- **Resume support** - Large files may fail mid-upload, should support resume
- **Progress tracking** - Show upload progress for large RAW files
- **Bandwidth management** - Don't saturate connection, may need throttling

### Storage Costs
- **Monitor usage** - Add metrics/logging for RAW storage usage
- **Lifecycle policies** - Automatically transition to cheaper storage
- **Cleanup** - Consider retention policies (delete after X years?)

### User Experience
- **Transparency** - Show RAW upload status in logs/status
- **Optional** - Make it opt-in so users aren't surprised by costs
- **Documentation** - Clearly document storage costs and options

### Code Changes Needed

1. **Config (`ghostroll/config.py`):**
   - Add `upload_raw_files: bool = False`
   - Add `raw_storage_class: str = "STANDARD"` (optional, for Glacier)

2. **Pipeline (`ghostroll/pipeline.py`):**
   - After copying RAW files to originals, conditionally add to upload queue
   - Upload to `{prefix}/originals/DCIM/{relative_path}`
   - Use existing upload deduplication logic

3. **Documentation:**
   - Update README with RAW upload option
   - Document storage costs
   - Add config examples

## Implementation: Glacier Lifecycle Policy

To automatically transition RAW files to cheaper Glacier storage after 30 days, configure an S3 lifecycle policy on your bucket.

### Option A: AWS Console

1. Go to your S3 bucket in AWS Console
2. Navigate to **Management** → **Lifecycle rules**
3. Click **Create lifecycle rule**
4. Configure:
   - **Rule name**: `raw-files-to-glacier`
   - **Rule scope**: **Apply to all objects in the bucket** (or use prefix filter: `sessions/*/originals/`)
   - **Transitions**:
     - **Transition to Glacier Instant Retrieval**: After 30 days
     - (Optional) **Transition to Glacier Deep Archive**: After 90 days (for even cheaper long-term storage)

### Option B: AWS CLI

Create a lifecycle policy JSON file:

```json
{
  "Rules": [
    {
      "Id": "raw-files-to-glacier",
      "Status": "Enabled",
      "Filter": {
        "Prefix": "sessions/"
      },
      "Transitions": [
        {
          "Days": 30,
          "StorageClass": "GLACIER_IR"
        }
      ]
    }
  ]
}
```

Then apply it:

```bash
aws s3api put-bucket-lifecycle-configuration \
  --bucket photo-ingest-project \
  --lifecycle-configuration file://lifecycle-policy.json
```

### Option C: Terraform/CloudFormation

If you're using infrastructure as code, add a lifecycle configuration:

**Terraform example:**
```hcl
resource "aws_s3_bucket_lifecycle_configuration" "raw_files" {
  bucket = aws_s3_bucket.ghostroll.id

  rule {
    id     = "raw-files-to-glacier"
    status = "Enabled"
    
    filter {
      prefix = "sessions/"
    }

    transition {
      days          = 30
      storage_class = "GLACIER_IR"
    }
  }
}
```

### Storage Class Options

- **GLACIER_IR** (Glacier Instant Retrieval): ~$0.004/GB/month
  - Retrieval: Immediate (milliseconds)
  - Best for: Files you might need occasionally but want to save on storage
  
- **GLACIER** (Glacier Flexible Retrieval): ~$0.0036/GB/month
  - Retrieval: 1-5 minutes (Expedited), 3-5 hours (Standard), 5-12 hours (Bulk)
  - Best for: Files you rarely need but want faster than Deep Archive

- **DEEP_ARCHIVE**: ~$0.00099/GB/month (cheapest)
  - Retrieval: 12 hours (Standard), 48 hours (Bulk)
  - Best for: Long-term archival, rarely accessed files

### Cost Comparison

For 3GB of RAW files per session:
- **S3 Standard**: ~$0.07/month
- **Glacier IR** (after 30 days): ~$0.012/month
- **Deep Archive** (after 90 days): ~$0.003/month

**Note:** Retrieval costs apply when downloading from Glacier:
- Glacier IR: $0.03/GB retrieved
- Glacier: $0.02-0.03/GB (depending on retrieval speed)
- Deep Archive: $0.02/GB retrieved

## Questions to Consider

1. **Do you want RAW files accessible via presigned URLs?** (for downloading later)
2. **What's your acceptable storage cost?** (helps choose storage class)
3. **How often will you access RAW files?** (affects Glacier vs Standard choice)
4. **Do you want automatic lifecycle management?** (transition to cheaper storage)
5. **Should RAW uploads be parallel with JPEG uploads?** (affects upload time)

