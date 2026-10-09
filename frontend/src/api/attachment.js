/** 附件接口（docs/API.md §7）：上传 / 删除 / 详情 / 列表。 */

import { http, downloadFile } from './http'

export function uploadAttachment(conversationId, file, { onProgress } = {}) {
  // 需要进度时走 XHR；否则用统一的 fetch 封装即可
  if (!onProgress) {
    const form = new FormData()
    form.append('conversation_id', String(conversationId))
    form.append('file', file)
    return http.post('/api/attachment/upload', undefined, { form })
  }

  return new Promise((resolve, reject) => {
    const form = new FormData()
    form.append('conversation_id', String(conversationId))
    form.append('file', file)
    const xhr = new XMLHttpRequest()
    xhr.open('POST', '/api/attachment/upload')
    xhr.withCredentials = true
    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable) onProgress(Math.round((event.loaded / event.total) * 100))
    }
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        try {
          resolve(JSON.parse(xhr.responseText))
        } catch {
          reject(new Error('上传响应解析失败'))
        }
      } else {
        let detail = `上传失败（HTTP ${xhr.status}）`
        try {
          const data = JSON.parse(xhr.responseText)
          if (data?.detail) detail = data.detail
        } catch {
          /* 保留默认提示 */
        }
        reject(new Error(detail))
      }
    }
    xhr.onerror = () => reject(new Error('上传失败：网络异常'))
    xhr.send(form)
  })
}

export function deleteAttachment(attachmentId) {
  return http.post('/api/attachment/delete', { attachment_id: attachmentId })
}

export function getAttachment(attachmentId) {
  return http.get('/api/attachment/get', { attachment_id: attachmentId })
}

export function listAttachments(conversationId) {
  return http.get('/api/attachment/ls', { conversation_id: conversationId })
}

/** 下载原始附件文件。 */
export function downloadAttachment(attachment) {
  return downloadFile(
    '/api/attachment/get',
    { attachment_id: attachment.attachment_id, download: true },
    attachment.file_name || 'attachment',
  )
}
