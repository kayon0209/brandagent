/**
 * Agent API 内部地址的唯一定位点。只能被服务端 route handler 引用——
 * 客户端代码不得导入本模块，内部拓扑不能进入浏览器 bundle。
 */
export function agentApiUrl(): string {
  return process.env.BRANDFLOW_AGENT_INTERNAL_URL || 'http://127.0.0.1:8000'
}
