Read, create, and update Google Slides presentations using the `gws slides` CLI.

## Rules
- Always use `gws slides` CLI — never MCP server, never curl
- Get the presentation first to map slide IDs before any update
- All updates use `batchUpdate` with `--json` for the body and `--params` for the presentation ID
- Slide IDs are strings (e.g., `"p"`, `"g1a2b3c4d"`) — always read them from the API, never guess

---

## Step 1 — Read the Presentation

```bash
gws slides presentations get \
  --params '{"presentationId": "PRES_ID"}' 2>/dev/null | python3 -c "
import json, sys
p = json.load(sys.stdin)
print('Title:', p['title'])
print('Slide size:', p['pageSize'])
print()
for i, slide in enumerate(p['slides']):
    sid = slide['objectId']
    # collect text from all shapes
    texts = []
    for el in slide.get('pageElements', []):
        if 'shape' in el:
            for te in el['shape'].get('text', {}).get('textElements', []):
                if 'textRun' in te:
                    t = te['textRun']['content'].strip()
                    if t: texts.append(t)
    print(f'Slide {i+1} [{sid}]: {\" | \".join(texts[:3])}')
"
```

## Step 2 — Get Slide Thumbnail (view a slide as image)

```bash
gws slides presentations pages getThumbnail \
  --params '{"presentationId": "PRES_ID", "pageObjectId": "SLIDE_ID"}' 2>/dev/null | python3 -c "
import json, sys
d = json.load(sys.stdin)
print('Thumbnail URL:', d['contentUrl'])
"
```

Then fetch the image:
```bash
curl -L "THUMBNAIL_URL" -o /tmp/slide_thumb.png
```

## Step 3 — batchUpdate Patterns

All updates use:
```bash
gws slides presentations batchUpdate \
  --params '{"presentationId": "PRES_ID"}' \
  --json '{"requests": [...]}'
```

### Add a new slide
```json
{
  "duplicateObject": {
    "objectId": "EXISTING_SLIDE_ID"
  }
}
```
Or insert a blank slide:
```json
{
  "createSlide": {
    "insertionIndex": 2,
    "slideLayoutReference": {"predefinedLayout": "TITLE_AND_BODY"}
  }
}
```
Layouts: `BLANK`, `TITLE_ONLY`, `TITLE_AND_BODY`, `TITLE_AND_TWO_COLUMNS`, `ONE_COLUMN_TEXT`, `MAIN_POINT`, `BIG_NUMBER`

### Add a text box
```json
{
  "createShape": {
    "objectId": "my_textbox_1",
    "shapeType": "TEXT_BOX",
    "elementProperties": {
      "pageObjectId": "SLIDE_ID",
      "size": {
        "width":  {"magnitude": 400, "unit": "PT"},
        "height": {"magnitude": 100, "unit": "PT"}
      },
      "transform": {
        "scaleX": 1, "scaleY": 1,
        "translateX": 50, "translateY": 50,
        "unit": "PT"
      }
    }
  }
}
```

### Insert text into a shape
```json
{
  "insertText": {
    "objectId": "SHAPE_ID",
    "insertionIndex": 0,
    "text": "Hello World"
  }
}
```

### Style text (bold, font size, color)
```json
{
  "updateTextStyle": {
    "objectId": "SHAPE_ID",
    "textRange": {"type": "ALL"},
    "style": {
      "bold": true,
      "fontSize": {"magnitude": 18, "unit": "PT"},
      "foregroundColor": {
        "opaqueColor": {"rgbColor": {"red": 0.1, "green": 0.1, "blue": 0.5}}
      },
      "fontFamily": "Roboto Mono"
    },
    "fields": "bold,fontSize,foregroundColor,fontFamily"
  }
}
```

### Set paragraph alignment
```json
{
  "updateParagraphStyle": {
    "objectId": "SHAPE_ID",
    "textRange": {"type": "ALL"},
    "style": {"alignment": "CENTER"},
    "fields": "alignment"
  }
}
```
Alignments: `START`, `CENTER`, `END`, `JUSTIFIED`

### Set shape background color
```json
{
  "updateShapeProperties": {
    "objectId": "SHAPE_ID",
    "shapeProperties": {
      "shapeBackgroundFill": {
        "solidFill": {
          "color": {"rgbColor": {"red": 0.929, "green": 0.929, "blue": 0.929}}
        }
      }
    },
    "fields": "shapeBackgroundFill"
  }
}
```

### Insert image onto a slide
```json
{
  "createImage": {
    "objectId": "my_image_1",
    "url": "https://drive.google.com/uc?export=download&id=FILE_ID",
    "elementProperties": {
      "pageObjectId": "SLIDE_ID",
      "size": {
        "width":  {"magnitude": 300, "unit": "PT"},
        "height": {"magnitude": 200, "unit": "PT"}
      },
      "transform": {
        "scaleX": 1, "scaleY": 1,
        "translateX": 100, "translateY": 150,
        "unit": "PT"
      }
    }
  }
}
```

### Delete a slide element
```json
{
  "deleteObject": {
    "objectId": "SHAPE_OR_IMAGE_ID"
  }
}
```

### Replace all text in presentation
```json
{
  "replaceAllText": {
    "containsText": {"text": "{{PLACEHOLDER}}", "matchCase": false},
    "replaceText": "Actual Value"
  }
}
```

### Set slide background color
```json
{
  "updatePageProperties": {
    "objectId": "SLIDE_ID",
    "pageProperties": {
      "pageBackgroundFill": {
        "solidFill": {
          "color": {"rgbColor": {"red": 0.95, "green": 0.95, "blue": 1.0}}
        }
      }
    },
    "fields": "pageBackgroundFill"
  }
}
```

## Step 4 — Create a New Presentation

```bash
gws slides presentations create \
  --params '{"fields": "presentationId,title"}' \
  --json '{"title": "My New Presentation"}'
```

## Step 5 — Read a Specific Slide (detailed)

```bash
gws slides presentations pages get \
  --params '{"presentationId": "PRES_ID", "pageObjectId": "SLIDE_ID"}' 2>/dev/null \
  | python3 -c "
import json, sys
page = json.load(sys.stdin)
for el in page.get('pageElements', []):
    eid = el['objectId']
    kind = list(el.keys() - {'objectId','size','transform','title','description'})
    print(f'Element [{eid}] type={kind}')
    if 'shape' in el:
        for te in el['shape'].get('text',{}).get('textElements',[]):
            if 'textRun' in te:
                print(f'  text: {repr(te[\"textRun\"][\"content\"])}')
"
```

## Common Errors

| Error | Cause | Fix |
|---|---|---|
| `400 Invalid JSON` | Used `--params` for body | Use `--json` for request body only |
| `objectId already exists` | Duplicate ID in createShape | Use unique IDs (e.g., add timestamp suffix) |
| `404 page not found` | Wrong slide ID | Re-fetch presentation to get current slide IDs |
| Image not showing | URL not publicly accessible | Upload to Drive, set `anyoneWithLink` reader permission |
| Text not updating | Wrong objectId | Read slide elements first to confirm shape IDs |
