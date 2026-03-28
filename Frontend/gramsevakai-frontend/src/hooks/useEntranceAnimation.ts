import { useEffect, useRef } from "react";
import { Animated, Easing } from "react-native";

export function useEntranceAnimation(delay = 0) {
  const opacity = useRef(new Animated.Value(0)).current;
  const translateY = useRef(new Animated.Value(18)).current;

  useEffect(() => {
    const animation = Animated.parallel([
      Animated.timing(opacity, {
        toValue: 1,
        duration: 380,
        delay,
        easing: Easing.out(Easing.cubic),
        useNativeDriver: true
      }),
      Animated.timing(translateY, {
        toValue: 0,
        duration: 420,
        delay,
        easing: Easing.out(Easing.cubic),
        useNativeDriver: true
      })
    ]);
    animation.start();
    return () => animation.stop();
  }, [delay, opacity, translateY]);

  return {
    opacity,
    transform: [{ translateY }]
  };
}
