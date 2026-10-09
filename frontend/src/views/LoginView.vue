<script setup>
/**
 * 登录页。
 *
 * 登录走独立认证中心的 OAuth2 授权码模式：点击按钮后整页跳转到后端
 * /auth/login，由后端带上 client_id / state 302 到认证中心授权页。
 * 前端全程不接触令牌，登录态只存在于 HttpOnly Cookie 中。
 */
import { computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { useUserStore } from '@/store/user'
import { WS_MESSAGE_TYPES, DEMO_QUESTIONS } from '@/utils/constants'

const route = useRoute()
const router = useRouter()
const user = useUserStore()

const systemName = computed(() => user.publicConfig?.system_name || '经营多轮归因分析系统')
const window_ = computed(() => user.publicConfig?.analysis_window)
const maxMb = computed(() => user.publicConfig?.upload_max_mb ?? 50)

onMounted(() => {
  // 回调落回登录页（例如直接访问 /login）时，若已有登录态就直接进工作台
  user.fetchMe({ silent: true }).then((me) => {
    if (me) router.replace(route.query.redirect || { name: 'workspace' })
  })
})

function handleLogin() {
  user.login()
}

const demoAccounts = [
  { role: '分析人员', username: 'analyst', password: 'Analyst@123', desc: '提问、分析、导出结果' },
  { role: '系统管理员', username: 'admin', password: 'Admin@123', desc: '额外拥有配置热重载与运维控制台' },
]
</script>

<template>
  <div class="login">
    <div class="login-left">
      <div class="brand">
        <div class="brand-logo">归因</div>
        <div>
          <div class="brand-title">{{ systemName }}</div>
          <div class="brand-sub">多轮对话驱动 · 结论可回溯至证据链</div>
        </div>
      </div>

      <h1 class="headline">
        经营问题，<br />
        用数据对话问出答案。
      </h1>
      <p class="lead">
        围绕商品目录、渠道投放、用户反馈、转化漏斗、营销活动、供应链履约六大预置场景，
        每一次提问都会自动拆解为分析步骤，实时展示工具调用链，最终产出问题定义、关键指标、
        证据链、归因结论、待补充数据与下一步行动建议六段式结果。
      </p>

      <div class="highlights">
        <div class="highlight">
          <el-icon><Connection /></el-icon>
          <div>
            <div class="hl-title">实时进度</div>
            <div class="hl-desc">长连接推送 8 类报文，步骤与工具调用逐条可见</div>
          </div>
        </div>
        <div class="highlight">
          <el-icon><DocumentChecked /></el-icon>
          <div>
            <div class="hl-title">标准化输出</div>
            <div class="hl-desc">六大模块结构化结果，支持 Markdown / JSON / Excel 导出</div>
          </div>
        </div>
        <div class="highlight">
          <el-icon><Refresh /></el-icon>
          <div>
            <div class="hl-title">配置热重载</div>
            <div class="hl-desc">分析参数与功能开关在线调整，无需重启服务</div>
          </div>
        </div>
      </div>

      <div class="demo-questions">
        <div class="dq-title">试试这些提问</div>
        <div v-for="q in DEMO_QUESTIONS.slice(0, 3)" :key="q" class="dq-item">
          <el-icon><ChatLineRound /></el-icon>
          <span>{{ q }}</span>
        </div>
      </div>
    </div>

    <div class="login-right">
      <div class="card">
        <div class="card-title">登录</div>
        <div class="card-sub">
          本系统不保存密码，登录由独立认证中心完成授权（OAuth2 授权码模式）。
        </div>

        <el-button class="login-btn" type="primary" size="large" @click="handleLogin">
          <el-icon><Key /></el-icon>
          前往认证中心登录
        </el-button>

        <el-alert
          v-if="route.query.redirect"
          class="tip"
          type="info"
          :closable="false"
          show-icon
          title="登录后会自动回到你刚才访问的页面"
        />

        <div class="accounts">
          <div class="accounts-title">演示账号</div>
          <div v-for="acc in demoAccounts" :key="acc.username" class="account">
            <div class="acc-role">{{ acc.role }}</div>
            <div class="acc-line jy-mono">
              账号 {{ acc.username }} / 口令 {{ acc.password }}
            </div>
            <div class="acc-desc">{{ acc.desc }}</div>
          </div>
        </div>

        <div v-if="window_" class="window">
          <el-icon><Calendar /></el-icon>
          演示数据窗口：基准期 {{ window_.base_period }}，异常期 {{ window_.anomaly_period }}
        </div>
        <div class="window">
          <el-icon><UploadFilled /></el-icon>
          附件单文件上限 {{ maxMb }} MB
        </div>
      </div>

      <div class="ws-note">
        <div class="ws-title">长连接推送的 {{ WS_MESSAGE_TYPES.length }} 类报文</div>
        <el-tag
          v-for="t in WS_MESSAGE_TYPES"
          :key="t.type"
          class="ws-tag"
          size="small"
          effect="plain"
        >
          {{ t.type }}
        </el-tag>
      </div>
    </div>
  </div>
</template>

<style scoped>
.login {
  display: flex;
  min-height: 100vh;
  background: linear-gradient(135deg, #eef2ff 0%, #f7f9ff 45%, #ffffff 100%);
}

.login-left {
  flex: 1.15;
  padding: 48px 56px;
  display: flex;
  flex-direction: column;
  justify-content: center;
  max-width: 760px;
}

.brand {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 36px;
}

.brand-logo {
  width: 42px;
  height: 42px;
  border-radius: 11px;
  background: linear-gradient(135deg, var(--jy-brand), #7a5cf0);
  color: #fff;
  font-weight: 700;
  display: flex;
  align-items: center;
  justify-content: center;
  letter-spacing: 1px;
}

.brand-title {
  font-size: 16px;
  font-weight: 600;
}

.brand-sub {
  font-size: 12px;
  color: var(--jy-text-secondary);
  margin-top: 3px;
}

.headline {
  font-size: 34px;
  line-height: 1.35;
  margin: 0 0 16px;
  color: var(--jy-text);
  letter-spacing: 1px;
}

.lead {
  font-size: 14px;
  line-height: 2;
  color: var(--jy-text-regular);
  margin: 0 0 28px;
  max-width: 600px;
}

.highlights {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
  gap: 14px;
  margin-bottom: 28px;
}

.highlight {
  display: flex;
  gap: 10px;
  background: rgba(255, 255, 255, 0.8);
  border: 1px solid var(--jy-border-light);
  border-radius: var(--jy-radius);
  padding: 12px 14px;
}

.highlight .el-icon {
  color: var(--jy-brand);
  font-size: 18px;
  margin-top: 1px;
}

.hl-title {
  font-size: 13px;
  font-weight: 600;
}

.hl-desc {
  font-size: 12px;
  color: var(--jy-text-secondary);
  margin-top: 4px;
  line-height: 1.7;
}

.demo-questions {
  border-left: 3px solid var(--jy-brand);
  padding-left: 14px;
}

.dq-title {
  font-size: 12px;
  color: var(--jy-text-placeholder);
  margin-bottom: 8px;
}

.dq-item {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  color: var(--jy-text-regular);
  margin-bottom: 6px;
}

.dq-item .el-icon {
  color: var(--jy-brand);
}

.login-right {
  flex: 1;
  min-width: 400px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 18px;
  padding: 48px 40px;
}

.card {
  width: 100%;
  max-width: 400px;
  background: #fff;
  border-radius: 14px;
  box-shadow: var(--jy-shadow-lg);
  padding: 28px;
}

.card-title {
  font-size: 20px;
  font-weight: 600;
}

.card-sub {
  font-size: 13px;
  color: var(--jy-text-secondary);
  line-height: 1.8;
  margin: 8px 0 20px;
}

.login-btn {
  width: 100%;
}

.tip {
  margin-top: 14px;
}

.accounts {
  margin-top: 22px;
  border-top: 1px dashed var(--jy-border);
  padding-top: 16px;
}

.accounts-title {
  font-size: 12px;
  color: var(--jy-text-placeholder);
  margin-bottom: 10px;
}

.account {
  background: var(--jy-bg);
  border-radius: var(--jy-radius-sm);
  padding: 10px 12px;
  margin-bottom: 8px;
}

.acc-role {
  font-size: 13px;
  font-weight: 600;
  color: var(--jy-brand-dark);
}

.acc-line {
  font-size: 12px;
  color: var(--jy-text-regular);
  margin-top: 4px;
}

.acc-desc {
  font-size: 12px;
  color: var(--jy-text-secondary);
  margin-top: 3px;
}

.window {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: var(--jy-text-secondary);
  margin-top: 10px;
}

.ws-note {
  max-width: 400px;
  text-align: center;
}

.ws-title {
  font-size: 12px;
  color: var(--jy-text-placeholder);
  margin-bottom: 8px;
}

.ws-tag {
  margin: 0 4px 6px 0;
  font-family: Consolas, 'Courier New', monospace;
}

@media (max-width: 1100px) {
  .login-left {
    display: none;
  }

  .login-right {
    min-width: 0;
    flex: 1;
  }
}
</style>
