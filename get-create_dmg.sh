#!/bin/bash
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"

VERSION="1.0"
APP_BUNDLE="겟슝.app"
VOLNAME="겟슝 ${VERSION}"
DIST_DIR="${DIR}/dist"
DMG_OUTPUT="${DIST_DIR}/Getshoong_${VERSION}.dmg"   # 사이트 링크와 일치
DMG_DIR="/tmp/getshoong_dmg_staging"
RW_DMG="/tmp/getshoong_rw.dmg"
MOUNT="/Volumes/${VOLNAME}"
SIGN_ID="${SIGN_ID:--}"

if [ ! -d "${DIST_DIR}/${APP_BUNDLE}" ]; then
  echo "없음: ${DIST_DIR}/${APP_BUNDLE} — 먼저 pyinstaller --noconfirm Getshoong.spec 실행"
  exit 1
fi
if [ "$SIGN_ID" != "-" ] && ! security find-identity -v -p codesigning 2>/dev/null | grep -q "$SIGN_ID"; then
  echo "인증서 '$SIGN_ID' 없음 → ad-hoc(-) 서명"
  SIGN_ID="-"
fi

# 같은 이름 볼륨이 이미 마운트돼 있으면 먼저 분리(중복 마운트로 배치 어긋남 방지)
if [ -d "$MOUNT" ]; then
  hdiutil detach "$MOUNT" >/dev/null 2>&1 || diskutil unmount force "$MOUNT" >/dev/null 2>&1 || true
  sleep 1
fi

# /tmp(비 iCloud)에서 정리 후 서명 → 서명 봉인 유지
rm -rf "$DMG_DIR"; mkdir -p "$DMG_DIR/.background"
cp -R "${DIST_DIR}/${APP_BUNDLE}" "$DMG_DIR/${APP_BUNDLE}"
find "$DMG_DIR/${APP_BUNDLE}" -name "._*" -delete 2>/dev/null || true
find "$DMG_DIR/${APP_BUNDLE}" -name ".DS_Store" -delete 2>/dev/null || true
xattr -cr "$DMG_DIR/${APP_BUNDLE}"
codesign --force --deep --sign "$SIGN_ID" "$DMG_DIR/${APP_BUNDLE}"
codesign --verify --deep --strict "$DMG_DIR/${APP_BUNDLE}" && echo "서명 유효(${SIGN_ID})"
ln -s /Applications "$DMG_DIR/Applications"

# 배경: 레티나 HiDPI TIFF(1x+2x), tiffutil 없으면 png
BG_FILE=""
if command -v tiffutil >/dev/null 2>&1 \
    && [ -f "$DIR/dmg_background.png" ] && [ -f "$DIR/dmg_background@2x.png" ]; then
  tiffutil -cathidpicheck "$DIR/dmg_background.png" "$DIR/dmg_background@2x.png" \
    -out "$DMG_DIR/.background/background.tiff" >/dev/null 2>&1 \
    && BG_FILE="background.tiff"
fi
if [ -z "$BG_FILE" ] && [ -f "$DIR/dmg_background.png" ]; then
  cp "$DIR/dmg_background.png" "$DMG_DIR/.background/background.png"; BG_FILE="background.png"
fi

# 쓰기 가능 DMG → 마운트 → Finder 배치 → 압축 변환
rm -f "$RW_DMG" "$DMG_OUTPUT"
hdiutil create -srcfolder "$DMG_DIR" -volname "$VOLNAME" -fs HFS+ -format UDRW -ov "$RW_DMG" >/dev/null
DEV="$(hdiutil attach -readwrite -noverify -noautoopen "$RW_DMG" | egrep '^/dev/' | sed 1q | awk '{print $1}')"
sleep 2

if [ -n "$BG_FILE" ]; then
  echo "🎨 설치 창 레이아웃 적용 중(터미널의 Finder 제어 권한 필요)..."
  set +e
  AS_OUT="$(osascript 2>&1 <<APPLESCRIPT
tell application "Finder"
  tell disk "$VOLNAME"
    open
    delay 2
    set current view of container window to icon view
    set toolbar visible of container window to false
    set statusbar visible of container window to false
    set the bounds of container window to {300, 140, 920, 600}
    set theViewOptions to the icon view options of container window
    set arrangement of theViewOptions to not arranged
    set icon size of theViewOptions to 112
    set text size of theViewOptions to 13
    set background picture of theViewOptions to file ".background:$BG_FILE"
    set position of item "$APP_BUNDLE" of container window to {160, 200}
    set position of item "Applications" of container window to {458, 200}
    update without registering applications
    delay 2
    close
  end tell
end tell
APPLESCRIPT
)"
  AS_RC=$?
  set -e
  if [ $AS_RC -ne 0 ]; then
    echo "⚠️  설치 창 꾸미기 실패(배경/배치 미적용). 사유: ${AS_OUT:-알 수 없음}"
    echo "    해결: 시스템 설정 → 개인정보 보호 및 보안 → 자동화 → 터미널 → Finder 허용 후 다시 실행"
  else
    echo "✅ 설치 창 레이아웃 적용 완료"
  fi
fi

[ -f "$MOUNT/.DS_Store" ] && echo "ℹ️  .DS_Store 기록됨" || echo "⚠️  .DS_Store 없음(배치 저장 안 됐을 수 있음)"
chmod -Rf go-w "$MOUNT" 2>/dev/null || true
sync; sleep 2
DET=""
for i in 1 2 3 4 5 6; do
  if hdiutil detach "$DEV" >/dev/null 2>&1; then DET=1; break; fi
  sleep 2
done
[ -n "$DET" ] || hdiutil detach "$DEV" -force >/dev/null 2>&1 || true
hdiutil convert "$RW_DMG" -format UDZO -imagekey zlib-level=9 -o "$DMG_OUTPUT" >/dev/null
rm -f "$RW_DMG"; rm -rf "$DMG_DIR"
echo "완료: $DMG_OUTPUT"
