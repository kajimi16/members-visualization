// 组织名统一配置：构建/开发时由 VITE_ORG_NAME 注入（与 Python 脚本的 GITHUB_ORG 保持一致），默认 Silver-yiyangyiyang
export const ORG_NAME = (import.meta.env.VITE_ORG_NAME || 'Silver-yiyangyiyang').replace(/^\/|\/$/g, '')

// 组织 GitHub 主页
export const ORG_GITHUB_URL = `https://github.com/${ORG_NAME}`

// 组织数据文件 URL（docs/public/data/<org>/ 下），自动拼接 BASE_URL
export const orgDataUrl = (subPath) => {
  const base = import.meta.env.BASE_URL || '/'
  return `${base}data/${ORG_NAME}/${subPath}`.replace(/\/+/g, '/')
}
