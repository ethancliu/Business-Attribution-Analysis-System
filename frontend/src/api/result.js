/** 分析结果接口（docs/API.md §9）：六大模块结构化结果 + md/json/xlsx 导出。 */

import { http, downloadFile } from './http'

/** 按任务取结构化结果；任务还没出结果时后端返回 404。 */
export function getResultByTask(taskId) {
  return http.get(`/api/results/${taskId}`)
}

/**
 * 下载导出文件。
 * @param {number} resultId
 * @param {'md'|'json'|'xlsx'} format
 */
export function downloadResult(resultId, format, fallbackName) {
  return downloadFile(
    '/api/results/download',
    { result_id: resultId, format },
    fallbackName || `分析结果.${format}`,
  )
}

export const EXPORT_FORMATS = [
  { value: 'md', label: 'Markdown 报告', ext: 'md' },
  { value: 'json', label: 'JSON 结构化数据', ext: 'json' },
  { value: 'xlsx', label: 'Excel 工作簿', ext: 'xlsx' },
]
