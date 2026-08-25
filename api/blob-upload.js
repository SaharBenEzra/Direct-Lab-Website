// Token endpoint for Vercel Blob's client-upload flow: the browser (see
// index.html) calls this first to get a short-lived, scoped upload token,
// then uploads the file bytes straight to Blob storage — never through this
// function, so file size isn't limited by Vercel's function payload limits.
//
// This is a Node.js function (not Python) because @vercel/blob/client's
// server-side helper (handleUpload) is a JS package; app.py handles every
// other route. See README's "Deploy to Vercel" section for how the two
// coexist and how to verify that in a real deployment.
import { handleUpload } from '@vercel/blob/client';

const ALLOWED_CONTENT_TYPES = [
  'application/pdf',
  'application/msword',
  'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
  'application/vnd.ms-powerpoint',
  'application/vnd.openxmlformats-officedocument.presentationml.presentation',
  'application/vnd.apple.keynote',
  'application/zip',
  'image/png',
  'image/jpeg',
  'image/svg+xml',
  'image/webp',
];

export default async function handler(request, response) {
  const body = request.body;

  try {
    const jsonResponse = await handleUpload({
      body,
      request,
      onBeforeGenerateToken: async () => ({
        allowedContentTypes: ALLOWED_CONTENT_TYPES,
        addRandomSuffix: true,
        // Matches the dropzone hints in index.html (25MB decks, 10MB logos).
        maximumSizeInBytes: 25 * 1024 * 1024,
      }),
      onUploadCompleted: async () => {
        // No-op: the browser reports the finished upload's URL straight to
        // /submit itself once every file is done, so there's nothing to do
        // here. (Kept as a hook in case that ever needs to change.)
      },
    });
    return response.status(200).json(jsonResponse);
  } catch (error) {
    return response.status(400).json({ error: error.message });
  }
}
