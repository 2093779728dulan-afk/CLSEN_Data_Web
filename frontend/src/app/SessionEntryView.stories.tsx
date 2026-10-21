import { useState } from "react";
import type { Meta, StoryObj } from "@storybook/react-vite";
import { LoginView, SessionStateView } from "./SessionEntryView";

type Scenario = "reference" | "filled" | "login-failure" | "submitting" | "checking" | "site-loading" | "site-failure";
function SessionEntryStory({ scenario }: { scenario: Scenario }) {
  const [username, setUsername] = useState(scenario === "reference" ? "" : "demo-reviewer");
  const [password, setPassword] = useState(scenario === "reference" ? "" : "fictional-only-password");
  const [error, setError] = useState<string | undefined>(scenario === "login-failure" ? "示例账号或密码不正确，请核对后重试。" : undefined);
  const [siteLoading, setSiteLoading] = useState(false);
  if (scenario === "checking") return <SessionStateView />;
  if (scenario === "site-loading" || siteLoading) return <SessionStateView message="正在读取当前站点配置…" />;
  if (scenario === "site-failure") return <SessionStateView error="示例站点配置读取失败，请稍后重试。" onRetry={() => setSiteLoading(true)} />;
  return <LoginView username={username} password={password} busy={scenario === "submitting"} error={error} onUsernameChange={setUsername} onPasswordChange={setPassword}
    onSubmit={event => { event.preventDefault(); setError(undefined); setSiteLoading(true); }} />;
}
const meta = { title: "Pages/Session Entry", component: SessionEntryStory, parameters: { layout: "fullscreen" }, args: { scenario: "reference" } } satisfies Meta<typeof SessionEntryStory>;
export default meta;
type Story = StoryObj<typeof meta>;
export const Reference: Story = {};
export const Filled: Story = { args: { scenario: "filled" } };
export const LoginFailure: Story = { args: { scenario: "login-failure" } };
export const Submitting: Story = { args: { scenario: "submitting" } };
export const Checking: Story = { args: { scenario: "checking" } };
export const SiteLoading: Story = { args: { scenario: "site-loading" } };
export const SiteFailure: Story = { args: { scenario: "site-failure" } };
