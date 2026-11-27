export const probeErrorLabels: Record<string, string> = {
  MODEL_UNAVAILABLE: "此 OpenCode 进程未识别该模型，请检查模型配置和凭据",
  CONNECTION_ERROR: "连接失败或超时",
  NO_OUTPUT: "未收到有效输出",
};

export function modelRef(id: string, variant: string): string {
  return variant ? `${id}#${variant}` : id;
}
