export interface CameraRect {
  x: number;
  y: number;
  width: number;
  height: number;
}

export interface CameraSize {
  width: number;
  height: number;
}

export interface PhotoCrop {
  originX: number;
  originY: number;
  width: number;
  height: number;
  normalized: CameraRect;
}

function clamp(value: number, minimum: number, maximum: number) {
  return Math.max(minimum, Math.min(maximum, value));
}

/**
 * Converte o retângulo desenhado sobre um preview `cover` para coordenadas da
 * fotografia realmente entregue pelo sensor. Assim o arquivo enviado contém o
 * mesmo enquadramento que o operador viu na tela.
 */
export function mapPreviewRectToPhotoCrop(
  preview: CameraSize,
  guide: CameraRect,
  photo: CameraSize,
  paddingRatio = 0.06,
): PhotoCrop | null {
  if (
    preview.width <= 0 || preview.height <= 0 ||
    photo.width <= 0 || photo.height <= 0 ||
    guide.width <= 0 || guide.height <= 0
  ) {
    return null;
  }

  const scale = Math.max(preview.width / photo.width, preview.height / photo.height);
  const renderedWidth = photo.width * scale;
  const renderedHeight = photo.height * scale;
  const hiddenX = Math.max((renderedWidth - preview.width) / 2, 0);
  const hiddenY = Math.max((renderedHeight - preview.height) / 2, 0);

  const paddedX = guide.x - guide.width * paddingRatio;
  const paddedY = guide.y - guide.height * paddingRatio;
  const paddedWidth = guide.width * (1 + paddingRatio * 2);
  const paddedHeight = guide.height * (1 + paddingRatio * 2);

  const sourceLeft = clamp((paddedX + hiddenX) / scale, 0, photo.width - 1);
  const sourceTop = clamp((paddedY + hiddenY) / scale, 0, photo.height - 1);
  const sourceRight = clamp((paddedX + paddedWidth + hiddenX) / scale, sourceLeft + 1, photo.width);
  const sourceBottom = clamp((paddedY + paddedHeight + hiddenY) / scale, sourceTop + 1, photo.height);

  const originX = Math.floor(sourceLeft);
  const originY = Math.floor(sourceTop);
  const width = Math.max(1, Math.ceil(sourceRight) - originX);
  const height = Math.max(1, Math.ceil(sourceBottom) - originY);

  return {
    originX,
    originY,
    width,
    height,
    normalized: {
      x: originX / photo.width,
      y: originY / photo.height,
      width: width / photo.width,
      height: height / photo.height,
    },
  };
}
