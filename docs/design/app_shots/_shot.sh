#!/bin/bash
# Screenshot a rendered HTML file at desktop + mobile widths.
# Uses an exact-width iframe that auto-grows to the page's full height, so we capture the
# whole page at a faithful CSS viewport width (avoids Chrome headless --window-size quirks
# with overflow-x:hidden + flex centering).
# usage: _shot.sh <html-file-basename-in-this-dir> <out-prefix>
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
HTML="$1"; OUT="$2"
frame() {
  local w=$1 png=$2
  cat > "$DIR/_frame.html" <<EOF
<!DOCTYPE html><html><head><meta charset="utf-8"><style>*{margin:0;padding:0}
html,body{background:#0a0d1c}iframe{width:${w}px;border:0;display:block}</style></head>
<body><iframe id="f" src="$HTML" scrolling="no"></iframe>
<script>
const f=document.getElementById('f');
function fit(){try{f.style.height=Math.max(f.contentDocument.documentElement.scrollHeight,
  f.contentDocument.body.scrollHeight)+'px';}catch(e){}}
f.onload=()=>{fit();setTimeout(fit,700);};
</script></body></html>
EOF
  "$CHROME" --headless=new --hide-scrollbars --disable-gpu \
    --virtual-time-budget=1600 --screenshot="$DIR/$png" \
    --window-size=$w,4000 "file://$DIR/_frame.html" 2>/dev/null
}
frame 1440 "${OUT}_desktop.png"
frame 390 "${OUT}_mobile.png"
rm -f "$DIR/_frame.html"
echo "shot $OUT"
