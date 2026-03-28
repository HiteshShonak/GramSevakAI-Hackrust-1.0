import React, { useEffect, useMemo, useRef, useState } from "react";
import {
  ActivityIndicator,
  Alert,
  KeyboardAvoidingView,
  Platform,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View
} from "react-native";
import { Ionicons } from "@expo/vector-icons";
import * as Speech from "expo-speech";

import { Screen } from "@/components/Screen";
import { useAuth } from "@/providers/AuthProvider";
import { useI18n } from "@/providers/I18nProvider";
import { sendChatMessage } from "@/services/chat";
import { startRecording, stopRecording, cancelRecording, sendVoiceMessage } from "@/services/voice";
import { colors, radii, shadows, typography } from "@/theme/tokens";
import * as Haptics from "expo-haptics";

/** Map GramSevak language codes → BCP-47 locale codes for TTS */
const LANG_TO_BCP47: Record<string, string> = {
  hi: "hi-IN", en: "en-IN", bn: "bn-IN", te: "te-IN", mr: "mr-IN",
  ta: "ta-IN", ur: "ur-IN", gu: "gu-IN", kn: "kn-IN", or: "or-IN",
  ml: "ml-IN", pa: "pa-IN", as: "as-IN", ne: "ne-IN", sd: "sd-IN",
  sa: "sa-IN", mai: "hi-IN", kok: "hi-IN", mni: "hi-IN", brx: "hi-IN",
  dg: "hi-IN", sat: "hi-IN", ks: "hi-IN", hry: "hi-IN",
};


type BubbleMessage = {
  id: string;
  role: "user" | "bot";
  text: string;
};

function createId() {
  return `${Date.now()}_${Math.random().toString(36).slice(2, 9)}`;
}

/**
 * Parse WhatsApp-style *bold* text into React Native Text elements.
 * Handles multiple bold segments in a single string.
 */
function renderFormattedText(
  text: string,
  baseStyle: object,
  boldExtra?: object
) {
  const parts = text.split(/(\*[^*]+\*)/g);
  if (parts.length === 1) {
    return <Text style={baseStyle}>{text}</Text>;
  }
  return (
    <Text style={baseStyle}>
      {parts.map((part, i) => {
        if (part.startsWith("*") && part.endsWith("*") && part.length > 2) {
          return (
            <Text key={i} style={[{ fontWeight: "700" }, boldExtra]}>
              {part.slice(1, -1)}
            </Text>
          );
        }
        return <Text key={i}>{part}</Text>;
      })}
    </Text>
  );
}

/** Quick-action prompt chips shown below messages when chat is idle */
const PROMPT_CHIPS_EN = [
  "🔍 Find schemes for me",
  "📋 Show my profile",
  "🛡️ Check a suspicious message",
];
const PROMPT_CHIPS_HI = [
  "🔍 मेरे लिए योजनाएं खोजो",
  "📋 मेरी प्रोफाइल दिखाओ",
  "🛡️ संदिग्ध संदेश जांचो",
];

/** Chips that need a follow-up paste step instead of direct send */
const SCAM_CHIP_EN = "Check a suspicious message";
const SCAM_CHIP_HI = "संदिग्ध संदेश जांचो";

/** Scam paste-mode prompts */
const SCAM_PROMPT_EN = "Please paste or type the suspicious message you received, and I'll check if it's real or fake.";
const SCAM_PROMPT_HI = "जो संदिग्ध संदेश आपको मिला है, उसे यहां पेस्ट करें या टाइप करें — मैं जांच करूंगा कि वह असली है या नकली।";


export function ChatbotScreen() {
  const { token } = useAuth();
  const { t, lang } = useI18n();
  const scrollRef = useRef<ScrollView>(null);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  /** When set, the NEXT user message carries this intent_hint */
  const [pendingIntent, setPendingIntent] = useState<"SCAM_CHECK" | null>(null);
  /** ID of the bot message currently being spoken aloud */
  const [speakingId, setSpeakingId] = useState<string | null>(null);
  /** Whether mic is currently recording */
  const [isRecordingState, setIsRecordingState] = useState(false);
  const [messages, setMessages] = useState<BubbleMessage[]>([
    {
      id: createId(),
      role: "bot",
      text: t("chatWelcome")
    }
  ]);

  // Cleanup TTS on unmount
  useEffect(() => () => { Speech.stop(); }, []);

  const canSend = useMemo(() => Boolean(input.trim()) && !sending, [input, sending]);
  const promptChips = lang === "en" ? PROMPT_CHIPS_EN : PROMPT_CHIPS_HI;

  /** Read a bot message aloud (or stop if already speaking it) */
  function handleSpeak(messageId: string, text: string) {
    if (speakingId === messageId) {
      Speech.stop();
      setSpeakingId(null);
      return;
    }
    // Strip markdown bold markers for cleaner speech
    const cleanText = text.replace(/\*/g, "");
    const locale = LANG_TO_BCP47[lang] || "hi-IN";
    Speech.stop();
    Speech.speak(cleanText, {
      language: locale,
      rate: 0.95,
      onDone: () => setSpeakingId(null),
      onStopped: () => setSpeakingId(null),
      onError: () => setSpeakingId(null),
    });
    setSpeakingId(messageId);
  }


  /** Handle chip tap — some chips need special behavior */
  function handleChipTap(chipLabel: string) {
    // Strip leading emoji: "🔍 Find schemes" → "Find schemes"
    const text = chipLabel.replace(/^[^\s]+\s/, "");

    // Scam chip → enter paste-mode
    if (text === SCAM_CHIP_EN || text === SCAM_CHIP_HI) {
      const prompt = lang === "en" ? SCAM_PROMPT_EN : SCAM_PROMPT_HI;
      setMessages((prev) => [
        ...prev,
        { id: createId(), role: "user", text: chipLabel },
        { id: createId(), role: "bot", text: prompt },
      ]);
      setPendingIntent("SCAM_CHECK");
      setTimeout(() => scrollRef.current?.scrollToEnd({ animated: true }), 30);
      return;
    }

    // All other chips → send directly
    void handleSend(text);
  }


  async function handleSend(forcedText?: string) {
    const text = (forcedText ?? input).trim();
    if (!text || !token || sending) {
      return;
    }

    const userBubble: BubbleMessage = { id: createId(), role: "user", text };
    setMessages((prev) => [...prev, userBubble]);
    setInput("");
    setSending(true);

    // Build request — attach pending intent hint if scam paste-mode was active
    const request: { message: string; language: string; intent_hint?: string } = {
      message: text,
      language: lang,
    };
    if (pendingIntent) {
      request.intent_hint = pendingIntent;
      setPendingIntent(null);
    }

    try {
      const response = await sendChatMessage(request as any, token);
      const botMessages = (response.messages || []).filter(Boolean);
      if (!botMessages.length) {
        setMessages((prev) => [
          ...prev,
          { id: createId(), role: "bot", text: t("chatNoReply") }
        ]);
      } else {
        setMessages((prev) => [
          ...prev,
          ...botMessages.map((msg) => ({ id: createId(), role: "bot" as const, text: msg }))
        ]);
      }
    } catch (error) {
      setMessages((prev) => [
        ...prev,
        { id: createId(), role: "bot", text: t("retry") }
      ]);
      Alert.alert("GramSevak AI", String(error));
    } finally {
      setSending(false);
      setTimeout(() => scrollRef.current?.scrollToEnd({ animated: true }), 30);
    }
  }

  function handleDeleteMessage(messageId: string) {
    Alert.alert("GramSevak AI", t("chatDeleteConfirm"), [
      { text: t("later"), style: "cancel" },
      {
        text: t("delete"),
        style: "destructive",
        onPress: () => {
          setMessages((prev) => prev.filter((item) => item.id !== messageId));
        }
      }
    ]);
  }

  /** Start/stop voice recording */
  async function handleVoiceRecord() {
    if (!token) return;
    if (isRecordingState) {
      // Stop and send
      setIsRecordingState(false);
      setSending(true);
      try {
        const uri = await stopRecording();
        if (!uri) { setSending(false); return; }
        await Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success);
        // Show recording indicator as user bubble
        setMessages((prev) => [
          ...prev,
          { id: createId(), role: "user", text: "🎤 " + (lang === "en" ? "Voice message" : "आवाज़ संदेश") }
        ]);
        const response = await sendVoiceMessage(uri, lang, token);
        const transcription = (response as any).transcription || "";
        // Replace the voice bubble with actual transcription
        if (transcription) {
          setMessages((prev) => {
            const updated = [...prev];
            const lastUserIdx = updated.map(m => m.role).lastIndexOf("user");
            if (lastUserIdx >= 0) updated[lastUserIdx] = { ...updated[lastUserIdx], text: transcription };
            return updated;
          });
        }
        const botMessages = (response.messages || []).filter(Boolean);
        if (botMessages.length) {
          setMessages((prev) => [
            ...prev,
            ...botMessages.map((msg) => ({ id: createId(), role: "bot" as const, text: msg }))
          ]);
        } else {
          setMessages((prev) => [
            ...prev,
            { id: createId(), role: "bot", text: t("chatNoReply") }
          ]);
        }
      } catch (error) {
        setMessages((prev) => [
          ...prev,
          { id: createId(), role: "bot", text: t("retry") }
        ]);
        await cancelRecording();
      } finally {
        setSending(false);
        setTimeout(() => scrollRef.current?.scrollToEnd({ animated: true }), 30);
      }
    } else {
      // Start recording
      try {
        await startRecording();
        setIsRecordingState(true);
        await Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium);
      } catch (error) {
        Alert.alert("GramSevak AI", String(error));
      }
    }
  }

  return (
    <Screen scroll={false}>
      <View style={styles.header}>
        <Text style={styles.headerTitle}>{t("chatTitle")}</Text>
        <Text style={styles.headerSubtitle}>{t("chatSubtitle")}</Text>
      </View>

      <KeyboardAvoidingView
        style={styles.chatWrap}
        behavior={Platform.OS === "ios" ? "padding" : undefined}
        keyboardVerticalOffset={10}
      >
        <ScrollView
          ref={scrollRef}
          contentContainerStyle={styles.messagesWrap}
          onContentSizeChange={() => scrollRef.current?.scrollToEnd({ animated: true })}
          keyboardShouldPersistTaps="handled"
          showsVerticalScrollIndicator={false}
        >
          {messages.map((message) => {
            const mine = message.role === "user";
            return (
              <View key={message.id} style={[styles.bubbleRow, mine ? styles.bubbleRowMine : styles.bubbleRowBot]}>
                {/* Bot avatar */}
                {!mine && (
                  <View style={styles.botAvatar}>
                    <Text style={styles.botAvatarText}>🏛️</Text>
                  </View>
                )}
                <Pressable
                  onLongPress={() => handleDeleteMessage(message.id)}
                  delayLongPress={220}
                  style={({ pressed }) => [
                    styles.bubble,
                    mine ? styles.bubbleMine : styles.bubbleBot,
                    pressed && styles.bubblePressed
                  ]}
                >
                  {renderFormattedText(
                    message.text,
                    [styles.bubbleText, mine ? styles.bubbleTextMine : styles.bubbleTextBot],
                    mine ? { color: "#fff" } : { color: colors.foreground }
                  )}
                  {/* TTS speaker icon on bot messages */}
                  {!mine && (
                    <Pressable
                      onPress={() => handleSpeak(message.id, message.text)}
                      hitSlop={8}
                      style={styles.speakerButton}
                    >
                      <Ionicons
                        name={speakingId === message.id ? "volume-mute" : "volume-medium"}
                        size={16}
                        color={speakingId === message.id ? colors.primaryDeep : colors.muted}
                      />
                    </Pressable>
                  )}
                </Pressable>
              </View>
            );
          })}

          {sending ? (
            <View style={styles.typingRow}>
              <View style={styles.botAvatar}>
                <Text style={styles.botAvatarText}>🏛️</Text>
              </View>
              <View style={styles.typingBubble}>
                <ActivityIndicator size="small" color={colors.primaryDeep} />
                <Text style={styles.typingText}>{t("chatTyping")}</Text>
              </View>
            </View>
          ) : null}

          {/* Prompt chips — show when not sending and few messages */}
          {!sending && messages.length <= 3 && (
            <View style={styles.chipsWrap}>
              {promptChips.map((chip) => (
                <Pressable
                  key={chip}
                  onPress={() => handleChipTap(chip)}
                  style={({ pressed }) => [styles.chip, pressed && styles.chipPressed]}
                >
                  <Text style={styles.chipText}>{chip}</Text>
                </Pressable>
              ))}
            </View>
          )}
        </ScrollView>

        <View style={styles.composerWrap}>
          {isRecordingState && (
            <View style={styles.recordingIndicator}>
              <View style={styles.recordingDot} />
              <Text style={styles.recordingText}>
                {lang === "en" ? "Recording..." : "रिकॉर्डिंग..."}
              </Text>
            </View>
          )}
          <TextInput
            value={input}
            onChangeText={setInput}
            placeholder={isRecordingState
              ? (lang === "en" ? "Recording... tap mic to stop" : "रिकॉर्डिंग... माइक दबाएं")
              : t("chatPlaceholder")}
            placeholderTextColor={isRecordingState ? "#ff4444" : colors.muted}
            style={[styles.input, isRecordingState && { borderColor: "#ff4444" + "60" }]}
            multiline
            maxLength={700}
            editable={!isRecordingState}
          />
          {input.trim() ? (
            /* Send button — shown when text is entered */
            <Pressable
              onPress={() => void handleSend()}
              disabled={!canSend}
              style={({ pressed }) => [
                styles.sendButton,
                !canSend && styles.sendButtonDisabled,
                pressed && canSend && styles.sendButtonPressed
              ]}
            >
              <Ionicons color="#fff" name="send" size={18} />
            </Pressable>
          ) : (
            /* Mic button — shown when input is empty */
            <Pressable
              onPress={() => void handleVoiceRecord()}
              disabled={sending}
              style={({ pressed }) => [
                styles.micButton,
                isRecordingState && styles.micButtonRecording,
                pressed && styles.micButtonPressed,
                sending && styles.sendButtonDisabled,
              ]}
            >
              <Ionicons
                color={isRecordingState ? "#fff" : colors.primaryDeep}
                name={isRecordingState ? "stop" : "mic"}
                size={22}
              />
            </Pressable>
          )}
        </View>
      </KeyboardAvoidingView>
    </Screen>
  );
}

const styles = StyleSheet.create({
  header: {
    marginTop: 8,
    marginBottom: 10,
    gap: 6
  },
  headerTitle: {
    color: colors.foreground,
    fontSize: 26,
    fontFamily: typography.display
  },
  headerSubtitle: {
    color: colors.muted,
    fontSize: 13,
    lineHeight: 20,
    fontFamily: typography.medium
  },
  chatWrap: {
    flex: 1,
    borderRadius: radii.xl,
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: "#f4f8f2",
    overflow: "hidden",
    marginBottom: 16,
    ...shadows.card
  },
  messagesWrap: {
    paddingHorizontal: 14,
    paddingVertical: 14,
    gap: 10,
    paddingBottom: 24
  },
  bubbleRow: {
    width: "100%",
    flexDirection: "row",
    alignItems: "flex-end",
    gap: 8
  },
  bubbleRowMine: {
    justifyContent: "flex-end"
  },
  bubbleRowBot: {
    justifyContent: "flex-start"
  },
  botAvatar: {
    width: 30,
    height: 30,
    borderRadius: 15,
    backgroundColor: colors.primaryDeep + "18",
    alignItems: "center",
    justifyContent: "center",
    marginBottom: 2
  },
  botAvatarText: {
    fontSize: 16
  },
  bubble: {
    maxWidth: "78%",
    borderRadius: 16,
    paddingHorizontal: 12,
    paddingVertical: 9,
    borderWidth: 1
  },
  bubbleMine: {
    backgroundColor: colors.primaryDeep,
    borderColor: colors.primaryDeep,
    borderBottomRightRadius: 6
  },
  bubbleBot: {
    backgroundColor: colors.card,
    borderColor: colors.border,
    borderBottomLeftRadius: 6
  },
  bubbleText: {
    fontSize: 14,
    lineHeight: 20,
    fontFamily: typography.medium
  },
  bubbleTextMine: {
    color: "#fff"
  },
  bubbleTextBot: {
    color: colors.foreground
  },
  bubblePressed: {
    opacity: 0.9
  },
  typingRow: {
    flexDirection: "row",
    alignItems: "flex-end",
    gap: 8
  },
  typingBubble: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
    borderRadius: 14,
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: colors.card,
    paddingHorizontal: 10,
    paddingVertical: 8
  },
  typingText: {
    color: colors.muted,
    fontSize: 12,
    fontFamily: typography.medium
  },
  chipsWrap: {
    flexDirection: "row",
    flexWrap: "wrap",
    gap: 8,
    marginTop: 6,
    paddingHorizontal: 2
  },
  chip: {
    borderRadius: 20,
    borderWidth: 1,
    borderColor: colors.primaryDeep + "40",
    backgroundColor: colors.primaryDeep + "0D",
    paddingHorizontal: 14,
    paddingVertical: 8
  },
  chipPressed: {
    backgroundColor: colors.primaryDeep + "22",
    borderColor: colors.primaryDeep
  },
  chipText: {
    fontSize: 13,
    color: colors.primaryDeep,
    fontFamily: typography.medium
  },
  composerWrap: {
    flexDirection: "row",
    flexWrap: "wrap",
    alignItems: "flex-end",
    gap: 8,
    paddingHorizontal: 12,
    paddingVertical: 12,
    borderTopWidth: 1,
    borderTopColor: colors.border,
    backgroundColor: colors.card
  },
  input: {
    flex: 1,
    minHeight: 44,
    maxHeight: 120,
    borderRadius: 14,
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: colors.background,
    paddingHorizontal: 12,
    paddingTop: 10,
    paddingBottom: 10,
    color: colors.foreground,
    fontSize: 14,
    fontFamily: typography.medium
  },
  sendButton: {
    width: 44,
    height: 44,
    borderRadius: 22,
    backgroundColor: colors.primaryDeep,
    alignItems: "center",
    justifyContent: "center"
  },
  sendButtonDisabled: {
    backgroundColor: colors.muted
  },
  sendButtonPressed: {
    opacity: 0.92
  },
  speakerButton: {
    alignSelf: "flex-end",
    marginTop: 4,
    paddingVertical: 2,
    paddingHorizontal: 4,
  },
  micButton: {
    width: 44,
    height: 44,
    borderRadius: 22,
    backgroundColor: colors.primaryDeep + "15",
    alignItems: "center",
    justifyContent: "center",
    borderWidth: 1,
    borderColor: colors.primaryDeep + "30",
  },
  micButtonRecording: {
    backgroundColor: "#ff4444",
    borderColor: "#ff4444",
  },
  micButtonPressed: {
    opacity: 0.85,
  },
  recordingIndicator: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    width: "100%",
    marginBottom: 6,
    paddingHorizontal: 4,
  },
  recordingDot: {
    width: 8,
    height: 8,
    borderRadius: 4,
    backgroundColor: "#ff4444",
  },
  recordingText: {
    fontSize: 12,
    color: "#ff4444",
    fontFamily: typography.medium,
  },
});
