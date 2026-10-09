<script setup>
/**
 * 分析结果六大模块的标准化渲染（需求 §13）。
 *
 * 一、问题定义 / 二、关键指标 / 三、证据链 / 四、归因结论 / 五、待补充数据 / 六、下一步行动建议
 * 三个文本模块按 Markdown 风格的分条（1. 2. 3. / - 开头）渲染成列表，其余按段落渲染。
 */
import { computed } from 'vue'

import { confidenceLevel, sourceTypeMeta } from '@/utils/constants'

const props = defineProps({
  result: { type: Object, required: true },
  compact: { type: Boolean, default: false },
})

/** 把文本按空行/编号拆成分条，便于阅读；拆不出分条时整体作为一段。 */
function toBlocks(text) {
  const raw = String(text ?? '').trim()
  if (!raw) return []
  const lines = raw.split('\n')
  const blocks = []
  let buffer = []

  const flush = () => {
    if (buffer.length) {
      blocks.push({ type: 'p', text: buffer.join('\n').trim() })
      buffer = []
    }
  }

  for (const line of lines) {
    const trimmed = line.trim()
    if (!trimmed) {
      flush()
      continue
    }
    const ordered = /^(\d+)[.、)]\s*(.*)$/.exec(trimmed)
    const bullet = /^[-*·]\s+(.*)$/.exec(trimmed)
    if (ordered) {
      flush()
      blocks.push({ type: 'li', index: ordered[1], text: ordered[2] })
    } else if (bullet) {
      flush()
      blocks.push({ type: 'bullet', text: bullet[1] })
    } else {
      buffer.push(trimmed)
    }
  }
  flush()
  return blocks
}

const problemBlocks = computed(() => toBlocks(props.result.problem_definition))
const conclusionBlocks = computed(() => toBlocks(props.result.conclusion_text))
const missingBlocks = computed(() => toBlocks(props.result.missing_data_text))
const actionBlocks = computed(() => toBlocks(props.result.next_action_text))

const metrics = computed(() => props.result.key_metrics || [])
const evidence = computed(() => props.result.evidence_list || [])

const sourceSummary = computed(() => {
  const map = new Map()
  evidence.value.forEach((e) => {
    const key = e.source_type || 'unknown'
    map.set(key, (map.get(key) || 0) + 1)
  })
  return [...map.entries()].map(([type, count]) => ({ ...sourceTypeMeta(type), count }))
})

const avgConfidence = computed(() => {
  if (!evidence.value.length) return null
  const sum = evidence.value.reduce((acc, e) => acc + (Number(e.confidence) || 0), 0)
  return sum / evidence.value.length
})
</script>

<template>
  <div class="modules" :class="{ 'modules--compact': compact }">
    <!-- 一、问题定义 -->
    <section class="module">
      <div class="module-head">
        <span class="module-no">一</span>
        <span class="module-title">问题定义</span>
      </div>
      <div class="module-body">
        <template v-for="(block, i) in problemBlocks" :key="i">
          <p v-if="block.type === 'p'" class="para jy-pre-wrap">{{ block.text }}</p>
          <div v-else class="li">
            <span class="li-mark">{{ block.index ? `${block.index}.` : '·' }}</span>
            <span class="jy-pre-wrap">{{ block.text }}</span>
          </div>
        </template>
        <div v-if="!problemBlocks.length" class="jy-muted">—</div>
      </div>
    </section>

    <!-- 二、关键指标 -->
    <section class="module">
      <div class="module-head">
        <span class="module-no">二</span>
        <span class="module-title">关键指标</span>
        <el-tag size="small" type="info" effect="plain" round>{{ metrics.length }}</el-tag>
      </div>
      <div class="module-body">
        <el-table v-if="metrics.length" :data="metrics" size="small" border stripe>
          <el-table-column type="index" label="#" width="48" align="center" />
          <el-table-column prop="metric_name" label="指标名称" min-width="180" show-overflow-tooltip />
          <el-table-column prop="metric_value" label="指标值" min-width="120" align="right">
            <template #default="{ row }">
              <span class="metric-value">{{ row.metric_value }}</span>
              <span v-if="row.metric_unit" class="metric-unit">{{ row.metric_unit }}</span>
            </template>
          </el-table-column>
          <el-table-column prop="metric_period" label="统计口径 / 周期" min-width="180" show-overflow-tooltip />
        </el-table>
        <div v-else class="jy-muted">本轮未产出关键指标。</div>
      </div>
    </section>

    <!-- 三、证据链 -->
    <section class="module">
      <div class="module-head">
        <span class="module-no">三</span>
        <span class="module-title">证据链</span>
        <el-tag size="small" type="info" effect="plain" round>{{ evidence.length }}</el-tag>
        <template v-if="sourceSummary.length">
          <el-tag
            v-for="s in sourceSummary"
            :key="s.label"
            size="small"
            effect="plain"
            :style="{ color: s.color, borderColor: s.color }"
          >
            {{ s.label }} {{ s.count }}
          </el-tag>
        </template>
        <span v-if="avgConfidence !== null" class="avg">
          平均置信度 {{ Math.round(avgConfidence * 100) }}%
        </span>
      </div>
      <div class="module-body">
        <div v-if="evidence.length" class="evidence">
          <div v-for="(ev, i) in evidence" :key="i" class="evidence-item">
            <div class="evidence-head">
              <span class="evidence-no">{{ i + 1 }}</span>
              <el-tag
                size="small"
                effect="plain"
                :style="{
                  color: sourceTypeMeta(ev.source_type).color,
                  borderColor: sourceTypeMeta(ev.source_type).color,
                }"
              >
                {{ sourceTypeMeta(ev.source_type).label }}
              </el-tag>
              <span class="evidence-source">{{ ev.source_name }}</span>
              <span class="evidence-metric">
                <el-icon><Aim /></el-icon>
                {{ ev.related_metric }}
              </span>
              <el-tag size="small" :type="confidenceLevel(ev.confidence).type" effect="light">
                置信度 {{ confidenceLevel(ev.confidence).percent }}%
              </el-tag>
            </div>
            <div class="evidence-text jy-pre-wrap">{{ ev.evidence_text }}</div>
          </div>
        </div>
        <div v-else class="jy-muted">本轮未产出证据。</div>
      </div>
    </section>

    <!-- 四、归因结论 -->
    <section class="module">
      <div class="module-head">
        <span class="module-no">四</span>
        <span class="module-title">归因结论</span>
      </div>
      <div class="module-body">
        <template v-for="(block, i) in conclusionBlocks" :key="i">
          <p v-if="block.type === 'p'" class="para jy-pre-wrap">{{ block.text }}</p>
          <div v-else class="li">
            <span class="li-mark">{{ block.index ? `${block.index}.` : '·' }}</span>
            <span class="jy-pre-wrap">{{ block.text }}</span>
          </div>
        </template>
        <div v-if="!conclusionBlocks.length" class="jy-muted">—</div>
      </div>
    </section>

    <!-- 五、待补充数据 -->
    <section class="module module--warning">
      <div class="module-head">
        <span class="module-no">五</span>
        <span class="module-title">待补充数据</span>
      </div>
      <div class="module-body">
        <template v-for="(block, i) in missingBlocks" :key="i">
          <p v-if="block.type === 'p'" class="para jy-pre-wrap">{{ block.text }}</p>
          <div v-else class="li">
            <el-icon class="li-icon"><WarningFilled /></el-icon>
            <span class="jy-pre-wrap">{{ block.text }}</span>
          </div>
        </template>
        <div v-if="!missingBlocks.length" class="jy-muted">本轮结论未声明数据缺口。</div>
      </div>
    </section>

    <!-- 六、下一步行动建议 -->
    <section class="module module--action">
      <div class="module-head">
        <span class="module-no">六</span>
        <span class="module-title">下一步行动建议</span>
      </div>
      <div class="module-body">
        <template v-for="(block, i) in actionBlocks" :key="i">
          <p v-if="block.type === 'p'" class="para jy-pre-wrap">{{ block.text }}</p>
          <div v-else class="li">
            <span class="li-mark li-mark--action">{{ block.index || '·' }}</span>
            <span class="jy-pre-wrap">{{ block.text }}</span>
          </div>
        </template>
        <div v-if="!actionBlocks.length" class="jy-muted">—</div>
      </div>
    </section>
  </div>
</template>

<style scoped>
.modules {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.module {
  background: var(--jy-bg-card);
  border: 1px solid var(--jy-border-light);
  border-radius: var(--jy-radius);
  box-shadow: var(--jy-shadow);
  overflow: hidden;
}

.module--warning {
  border-left: 3px solid var(--jy-warning);
}

.module--action {
  border-left: 3px solid var(--jy-brand);
}

.module-head {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 16px;
  background: linear-gradient(90deg, #f7f9ff, #ffffff);
  border-bottom: 1px solid var(--jy-border-light);
  flex-wrap: wrap;
}

.module--warning .module-head {
  background: linear-gradient(90deg, #fffaf1, #ffffff);
}

.module--action .module-head {
  background: linear-gradient(90deg, #f4f7ff, #ffffff);
}

.module-no {
  width: 20px;
  height: 20px;
  border-radius: 50%;
  background: var(--jy-brand);
  color: #fff;
  font-size: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.module--warning .module-no {
  background: var(--jy-warning);
}

.module-title {
  font-size: 14px;
  font-weight: 600;
}

.avg {
  margin-left: auto;
  font-size: 12px;
  color: var(--jy-text-secondary);
}

.module-body {
  padding: 14px 16px;
}

.para {
  margin: 0 0 10px;
  font-size: 14px;
  line-height: 1.85;
  color: var(--jy-text-regular);
}

.para:last-child {
  margin-bottom: 0;
}

.li {
  display: flex;
  gap: 8px;
  font-size: 14px;
  line-height: 1.85;
  color: var(--jy-text-regular);
  margin-bottom: 6px;
}

.li-mark {
  flex: 0 0 auto;
  color: var(--jy-brand);
  font-weight: 600;
}

.li-mark--action {
  min-width: 18px;
  height: 18px;
  border-radius: 50%;
  background: var(--jy-brand-soft);
  color: var(--jy-brand);
  font-size: 11px;
  display: flex;
  align-items: center;
  justify-content: center;
  margin-top: 5px;
}

.li-icon {
  color: var(--jy-warning);
  margin-top: 5px;
}

.metric-value {
  font-weight: 600;
  color: var(--jy-brand-dark);
}

.metric-unit {
  margin-left: 3px;
  font-size: 12px;
  color: var(--jy-text-secondary);
}

.evidence {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.evidence-item {
  border: 1px solid var(--jy-border-light);
  border-radius: var(--jy-radius-sm);
  padding: 10px 12px;
  background: #fcfcfe;
}

.evidence-head {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  margin-bottom: 6px;
}

.evidence-no {
  width: 18px;
  height: 18px;
  border-radius: 4px;
  background: var(--jy-brand-soft);
  color: var(--jy-brand);
  font-size: 11px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.evidence-source {
  font-size: 12px;
  color: var(--jy-text-secondary);
  font-family: Consolas, 'Courier New', monospace;
}

.evidence-metric {
  display: flex;
  align-items: center;
  gap: 3px;
  font-size: 12px;
  color: var(--jy-text-regular);
}

.evidence-text {
  font-size: 13px;
  line-height: 1.75;
  color: var(--jy-text-regular);
}
</style>
