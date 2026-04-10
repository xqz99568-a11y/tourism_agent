import { Providers } from "@/components/providers";
import { ChatPage } from "@/features/chat";

export default function HomePage() {
  return (
    <Providers>
      <ChatPage />
    </Providers>
  );
}
