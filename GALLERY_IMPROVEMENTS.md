# Gallery Page Improvement Recommendations

## Overview
This document identifies areas for improvement in the gallery page implementation (`ghostroll/gallery.py`).

## 1. Mobile Experience Enhancements

### 1.1 Header Layout on Small Screens
**Issue**: The `.top` header uses `justify-content:space-between` which can cause layout issues on very small screens when the title and meta info don't fit.

**Recommendation**: Add responsive breakpoint to stack header elements vertically on mobile:
```css
@media (max-width: 600px) {
  .top { flex-direction: column; gap: 8px; }
  .meta { font-size: 12px; }
}
```

### 1.2 Lightbox Button Size
**Issue**: Lightbox buttons (Prev/Next/Close) may be too small for touch targets on mobile (minimum 44x44px recommended).

**Recommendation**: Increase button size and padding on mobile:
```css
@media (max-width: 600px) {
  .lb-btn { padding: 12px 16px; min-height: 44px; font-size: 14px; }
  .lb-bar { flex-wrap: wrap; gap: 12px; }
}
```

### 1.3 Touch Gestures
**Issue**: No swipe gestures for navigating between images in lightbox on mobile.

**Recommendation**: Add touch event handlers for swipe left/right:
- Track touchstart, touchmove, touchend events
- Detect swipe direction and distance
- Navigate to next/prev on swipe threshold

### 1.4 Viewport Height Issues
**Issue**: Mobile browsers have dynamic viewport heights (address bar shows/hides), which can cause layout issues.

**Recommendation**: Use CSS viewport units that account for mobile browser chrome:
```css
.lb { height: 100dvh; } /* Dynamic viewport height */
```

### 1.5 Safe Area Insets
**Issue**: Notched devices (iPhone X+) may have content hidden behind notches.

**Recommendation**: Add safe area insets:
```css
.wrap { padding: max(18px, env(safe-area-inset-top)) max(18px, env(safe-area-inset-right)) max(18px, env(safe-area-inset-bottom)) max(18px, env(safe-area-inset-left)); }
```

## 2. Performance Optimizations

### 2.1 Image Preloading in Lightbox
**Issue**: When opening lightbox, only current image loads. Next/previous images load on navigation, causing delay.

**Recommendation**: Preload adjacent images when lightbox opens:
```javascript
function preloadAdjacent() {
  if (idx + 1 < tiles.length) {
    const nextImg = new Image();
    nextImg.src = tiles[idx + 1].dataset.full;
  }
  if (idx - 1 >= 0) {
    const prevImg = new Image();
    prevImg.src = tiles[idx - 1].dataset.full;
  }
}
```

### 2.2 Progressive Image Loading
**Issue**: No placeholder or blur-up effect while images load.

**Recommendation**: 
- Add placeholder background color or skeleton
- Optionally implement blur-up technique with low-quality image previews

### 2.3 Intersection Observer for Lazy Loading
**Issue**: Uses native `loading="lazy"` but could be more efficient with Intersection Observer.

**Recommendation**: Implement Intersection Observer for better control over when images load, especially useful for very long galleries.

### 2.4 Image Loading Error Handling
**Issue**: No visual feedback when images fail to load.

**Recommendation**: Add error handling:
```javascript
img.addEventListener('error', function() {
  this.alt = 'Failed to load image';
  this.style.background = 'var(--muted)';
  // Show error icon or message
});
```

## 3. User Experience Improvements

### 3.1 Image Counter in Lightbox
**Issue**: Lightbox doesn't show current position (e.g., "3 of 10").

**Recommendation**: Add image counter to lightbox bar:
```html
<div id="lbCounter" style="opacity:.8;font-size:12px">1 / 10</div>
```

### 3.2 Loading State in Lightbox
**Issue**: No indication when full-resolution image is loading in lightbox.

**Recommendation**: Show loading spinner or progress indicator while `lbImg` loads.

### 3.3 Individual Image Download
**Issue**: Only "Download all" button exists. No way to download individual images.

**Recommendation**: Add download button in lightbox that downloads current image.

### 3.4 Share Functionality
**Issue**: No way to share individual images or the gallery link.

**Recommendation**: 
- Add share button in lightbox (uses Web Share API if available)
- Add share button in header for gallery link

### 3.5 Pinch-to-Zoom in Lightbox
**Issue**: Mobile users can't zoom into images in lightbox.

**Recommendation**: Implement pinch-to-zoom gesture support for mobile lightbox images.

### 3.6 Image Aspect Ratio Preservation
**Issue**: Images use `object-fit:contain` which is good, but very tall images might be too small.

**Recommendation**: Consider `object-fit:cover` with max-height constraint, or allow user to toggle between contain/cover.

## 4. Accessibility Improvements

### 4.1 Keyboard Focus Management
**Issue**: When lightbox opens, focus doesn't move to lightbox. When it closes, focus doesn't return to triggering element.

**Recommendation**: 
```javascript
function openAt(i) {
  // ... existing code ...
  document.getElementById('closeBtn').focus(); // Move focus to close button
}
function close() {
  // ... existing code ...
  tiles[idx].focus(); // Return focus to triggering tile
}
```

### 4.2 ARIA Labels
**Issue**: Navigation buttons have text but could benefit from more descriptive ARIA labels.

**Recommendation**: 
```html
<button class="lb-btn" id="prevBtn" type="button" aria-label="Previous image">← Prev</button>
<button class="lb-btn" id="nextBtn" type="button" aria-label="Next image">Next →</button>
```

### 4.3 Alt Text Quality
**Issue**: Alt text uses `title` which may be a file path (not descriptive for screen readers).

**Recommendation**: Generate more descriptive alt text, or use subtitle if available, or provide fallback like "Gallery image 1".

### 4.4 Skip Links
**Issue**: No skip link for keyboard users to jump to main content.

**Recommendation**: Add skip link at top of page (hidden until focused).

### 4.5 Focus Visible States
**Issue**: Focus outline exists but could be more prominent.

**Recommendation**: Ensure all interactive elements have clear focus indicators.

## 5. Code Quality & Maintainability

### 5.1 Inline Styles
**Issue**: Some styles are inline in HTML (e.g., `style="opacity:.8;font-size:12px"`).

**Recommendation**: Move all styles to CSS classes for better maintainability.

### 5.2 CSS Organization
**Issue**: All CSS is in one large string, making it hard to read and maintain.

**Recommendation**: Consider breaking into logical sections with comments, or extract to separate template.

### 5.3 JavaScript Error Handling
**Issue**: No error handling if DOM elements are missing.

**Recommendation**: Add null checks and graceful degradation:
```javascript
const lb = document.getElementById('lb');
if (!lb) return; // Early exit if element missing
```

### 5.4 Event Listener Cleanup
**Issue**: Event listeners are added but never removed (though not critical for static pages).

**Recommendation**: For future dynamic updates, implement proper cleanup.

## 6. Visual Design Enhancements

### 6.1 Image Hover Effects
**Issue**: No visual feedback on image hover (desktop).

**Recommendation**: Add subtle hover effect:
```css
.tile:hover { transform: translateY(-2px); box-shadow: 0 12px 40px rgba(0,0,0,.4); }
.tile { transition: transform 0.2s, box-shadow 0.2s; }
```

### 6.2 Loading Placeholder
**Issue**: Images show blank space while loading.

**Recommendation**: Add skeleton loader or placeholder with aspect ratio:
```css
.tile img { background: linear-gradient(90deg, #f0f0f0 25%, #e0e0e0 50%, #f0f0f0 75%); background-size: 200% 100%; }
```

### 6.3 Empty State Enhancement
**Issue**: Empty state is functional but could be more visually appealing.

**Recommendation**: Add icon or illustration to empty state.

## 7. Browser Compatibility

### 7.1 CSS Feature Support
**Issue**: Uses modern CSS features that may not work in older browsers.

**Recommendation**: 
- Add fallbacks for CSS custom properties
- Test in older browsers or add polyfills if needed

### 7.2 JavaScript Modern Syntax
**Issue**: Uses arrow functions, template literals, const/let which may not work in very old browsers.

**Recommendation**: Document minimum browser requirements or consider transpilation if needed.

## 8. Progressive Enhancement

### 8.1 No-JavaScript Fallback
**Issue**: Lightbox requires JavaScript. Without it, clicking images just navigates to full image (which works, but not ideal).

**Recommendation**: Ensure basic functionality works without JS (it does), but could add `<noscript>` message explaining lightbox won't work.

### 8.2 Network-Aware Loading
**Issue**: No consideration for slow network connections.

**Recommendation**: 
- Detect connection speed (if available via Network Information API)
- Adjust image quality or loading strategy based on connection

## Priority Recommendations

### High Priority
1. ✅ Mobile-friendly layout (already done)
2. ✅ Remove overlay labels (already done)
3. Touch gestures for lightbox navigation
4. Image counter in lightbox
5. Better mobile button sizes
6. Keyboard focus management

### Medium Priority
1. Image preloading in lightbox
2. Loading states and error handling
3. Individual image download
4. Improved accessibility (ARIA labels, focus management)
5. Viewport height fixes for mobile

### Low Priority
1. Progressive image loading
2. Share functionality
3. Pinch-to-zoom
4. Code organization improvements
5. Visual enhancements (hover effects, placeholders)


